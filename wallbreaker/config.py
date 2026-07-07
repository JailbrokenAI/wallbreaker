from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_NAMES = ("config.toml", "config.example.toml")


class ConfigError(Exception):
    pass


# Substrings that mark an OpenRouter image-GENERATION model (output_modalities includes
# image). Used to auto-set modality="image" when the target model is swapped at runtime,
# so pointing the target at e.g. google/gemini-3-pro-image "just works" without editing
# config.toml. The explicit override always wins over this guess.
_IMAGE_MODEL_HINTS = (
    "image", "flux", "dall-e", "dalle", "stable-diffusion", "sdxl", "sd3",
    "seedream", "seededit", "imagen", "ideogram", "playground-v", "nano-banana",
    "recraft", "grok-2-image",
)


def looks_like_image_model(model_id: str) -> bool:
    low = (model_id or "").lower()
    return any(h in low for h in _IMAGE_MODEL_HINTS)


def resolve_target_modality(model_id: str, explicit: str | None = None) -> str:
    """Pick the modality for a target whose model was swapped at runtime.

    Explicit ('text'/'image') wins; else auto-detect image-gen models by id; else 'text'.
    Derived purely from the new model (not the old target's modality) so a swap never
    leaves a stale modality. This is the fix for: a runtime target override swapped the
    model to an image model but left modality='text', so image tools refused it.
    """
    if explicit in ("text", "image"):
        return explicit
    return "image" if looks_like_image_model(model_id) else "text"


@dataclass
class Endpoint:
    name: str
    protocol: str
    base_url: str
    model: str
    api_key_env: str = ""
    api_key: str = ""
    provider: tuple[str, ...] = ()
    timeout: float = 0.0
    modality: str = "text"
    reasoning: bool = False
    # how the system prompt is delivered to THIS endpoint:
    #   "default" - native (OpenAI system message / Anthropic top-level system)
    #   "merge"   - fold the system text into the first user turn (for targets that
    #               accept a system prompt but are hardened against it - move the
    #               persona to the user channel where the model is actually steerable)
    #   "drop"    - discard the system prompt entirely
    system_mode: str = "default"
    # claude-code only: a file whose contents become the brain's base system prompt
    # (passed to the CLI as --system-prompt-file); the harness tool protocol is appended.
    system_prompt_file: str = ""

    def resolved_key(self) -> str:
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.environ.get(self.api_key_env, "")
        return ""

    def require_key(self) -> str:
        key = self.resolved_key()
        if not key:
            raise ConfigError(
                f"No API key for endpoint '{self.name}'. "
                f"Set env var '{self.api_key_env}' or pass --api-key."
            )
        return key


@dataclass
class MCPServer:
    """A Model Context Protocol server the harness connects to over stdio.

    Its tools are proxied into the agent's ToolRegistry by tools/mcp_bridge.py.
    """

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    tool_prefix: str = ""
    cwd: str = ""


@dataclass
class Config:
    default_profile: str
    profiles: dict[str, Endpoint] = field(default_factory=dict)
    target: Endpoint | None = None
    judge: Endpoint | None = None
    art: Endpoint | None = None
    mcp_servers: list[MCPServer] = field(default_factory=list)
    path: Path | None = None

    def profile(self, name: str | None = None) -> Endpoint:
        key = name or self.default_profile
        if key not in self.profiles:
            available = ", ".join(self.profiles) or "(none)"
            raise ConfigError(f"Unknown profile '{key}'. Available: {available}")
        return self.profiles[key]


def doctor_report(config: Config) -> tuple[str, bool]:
    """Validate a loaded config and return (checklist, all_ok)."""
    lines: list[str] = ["Wallbreaker config check", "=" * 40]
    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        mark = "ok " if passed else "XX "
        ok = ok and passed
        lines.append(f"[{mark}] {label}" + (f" - {detail}" if detail else ""))

    check("profiles defined", bool(config.profiles), f"{len(config.profiles)} found")
    check(
        f"default_profile '{config.default_profile}' exists",
        config.default_profile in config.profiles,
    )
    for name, ep in config.profiles.items():
        has_key = bool(ep.resolved_key())
        detail = f"{ep.model} @ {ep.base_url}"
        if not has_key:
            detail += f" (no key: set {ep.api_key_env or 'api_key'})"
        check(f"profile '{name}' key resolves", has_key, detail)

    if config.target is None:
        lines.append("[note] no [target] - set one or use /target before attacking")
    else:
        modality_note = (
            " (image-gen target)" if config.target.modality == "image" else ""
        )
        check(
            "target key resolves",
            bool(config.target.resolved_key()),
            f"{config.target.model} @ {config.target.base_url}{modality_note}",
        )

    if config.judge is None:
        lines.append("[note] no [judge] - grading falls back to the default profile")
    else:
        check(
            "judge key resolves",
            bool(config.judge.resolved_key()),
            f"{config.judge.model} @ {config.judge.base_url}",
        )

    if config.art is None:
        lines.append(
            "[note] no [art] - generate_session_card falls back to the 'openrouter' "
            "profile (if any) or a local renderer"
        )
    else:
        check(
            "art key resolves",
            bool(config.art.resolved_key()),
            f"{config.art.model} @ {config.art.base_url}",
        )

    lines.append("=" * 40)
    lines.append("READY" if ok else "NOT READY - fix the XX lines above")
    return "\n".join(lines), ok


def _endpoint_from_table(name: str, table: dict) -> Endpoint:
    protocol = str(table.get("protocol", "")).lower()
    # claude-code drives the local `claude` CLI - it authenticates itself and needs no
    # base_url/api_key, so only protocol+model are required for it.
    required = ("protocol", "model") if protocol == "claude-code" else ("protocol", "base_url", "model")
    missing = [k for k in required if k not in table]
    if missing:
        raise ConfigError(f"Endpoint '{name}' missing keys: {', '.join(missing)}")
    if protocol not in ("openai", "anthropic", "claude-code"):
        raise ConfigError(
            f"Endpoint '{name}' has invalid protocol '{protocol}' "
            f"(expected 'openai', 'anthropic', or 'claude-code')"
        )
    modality = str(table.get("modality", "text")).lower()
    if modality not in ("text", "image"):
        raise ConfigError(
            f"Endpoint '{name}' has invalid modality '{modality}' "
            f"(expected 'text' or 'image')"
        )
    if modality == "image" and protocol != "openai":
        raise ConfigError(
            f"Endpoint '{name}': modality 'image' requires protocol 'openai' "
            f"(OpenRouter image generation rides the chat-completions API)"
        )
    provider = table.get("provider")
    if isinstance(provider, str):
        provider = (provider,)
    elif isinstance(provider, list):
        provider = tuple(str(p) for p in provider)
    else:
        provider = ()
    return Endpoint(
        name=name,
        protocol=protocol,
        base_url=str(table.get("base_url", "")).rstrip("/"),
        model=str(table["model"]),
        api_key_env=str(table.get("api_key_env", "")),
        api_key=str(table.get("api_key", "")),
        provider=provider,
        timeout=float(table.get("timeout", 0) or 0),
        modality=modality,
        reasoning=bool(table.get("reasoning", False)),
        system_mode=str(table.get("system_mode", "default")).lower(),
        system_prompt_file=str(table.get("system_prompt_file", "")),
    )


def _mcp_server_from_table(table: dict) -> MCPServer:
    name = str(table.get("name", "")).strip()
    command = str(table.get("command", "")).strip()
    if not name or not command:
        raise ConfigError("Each [[mcp.servers]] needs a 'name' and a 'command'.")
    raw_args = table.get("args", [])
    if isinstance(raw_args, str):
        args: tuple[str, ...] = (raw_args,)
    elif isinstance(raw_args, list):
        args = tuple(str(a) for a in raw_args)
    else:
        args = ()
    env_table = table.get("env", {})
    env = {str(k): str(v) for k, v in env_table.items()} if isinstance(env_table, dict) else {}
    return MCPServer(
        name=name,
        command=command,
        args=args,
        env=env,
        enabled=bool(table.get("enabled", True)),
        tool_prefix=str(table.get("tool_prefix", "")),
        cwd=str(table.get("cwd", "")),
    )


def _load_mcp_servers(data: dict) -> list[MCPServer]:
    mcp_table = data.get("mcp", {})
    if not isinstance(mcp_table, dict):
        return []
    servers = mcp_table.get("servers", [])
    if not isinstance(servers, list):
        return []
    return [_mcp_server_from_table(s) for s in servers if isinstance(s, dict)]


def find_config(start: Path | None = None) -> Path | None:
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        for name in DEFAULT_CONFIG_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def load_config(path: str | Path | None = None) -> Config:
    config_path = Path(path) if path else find_config()
    if config_path is None or not config_path.is_file():
        raise ConfigError(
            "No config file found. Copy config.example.toml to config.toml."
        )
    with open(config_path, "rb") as handle:
        data = tomllib.load(handle)

    profiles_table = data.get("profiles", {})
    if not profiles_table:
        raise ConfigError(f"No [profiles.*] defined in {config_path}")

    profiles = {
        name: _endpoint_from_table(name, table)
        for name, table in profiles_table.items()
    }

    default_profile = data.get("default_profile") or next(iter(profiles))
    if default_profile not in profiles:
        raise ConfigError(f"default_profile '{default_profile}' is not defined")

    target = None
    if "target" in data:
        target = _endpoint_from_table("target", data["target"])

    judge = None
    if "judge" in data:
        judge = _endpoint_from_table("judge", data["judge"])

    art = None
    if "art" in data:
        art = _endpoint_from_table("art", data["art"])

    return Config(
        default_profile=default_profile,
        profiles=profiles,
        target=target,
        judge=judge,
        art=art,
        mcp_servers=_load_mcp_servers(data),
        path=config_path,
    )
