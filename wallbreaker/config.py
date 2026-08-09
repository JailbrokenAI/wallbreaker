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
    # a file whose contents become the brain's operator system prompt, prepended to the
    # harness instructions (prompts.compose_system). For claude-code it is passed to the CLI
    # as --system-prompt-file; for API brains it is folded into the system prompt.
    system_prompt_file: str = ""
    # Inline operator prompt supplied by an agent profile. Provider connection
    # records never persist this field; it exists only on resolved, run-scoped
    # endpoints.
    system_prompt: str = ""
    # anthropic-protocol auth header: "x-api-key" (native Anthropic, default) or "bearer"
    # (Authorization: Bearer <key>) for third-party proxies (tokies.cc etc.) that use the
    # ANTHROPIC_AUTH_TOKEN scheme instead of a native Anthropic key.
    auth_style: str = "x-api-key"
    # Optional compatibility paths discovered from provider documentation. Empty
    # values retain the protocol defaults used by the provider implementations.
    inference_path: str = ""
    models_path: str = ""
    # explicit override for this model's swarm jailbreak system prompt (a file path). When
    # unset, the swarm resolves library/jailbreaks/<model-id>.md by convention. Lets a
    # profile pin a version-specific file (e.g. jb/openai/gpt-5.6-sol.md).
    jailbreak_file: str = ""
    # prompt caching (Anthropic-protocol): mark the static system prompt + tool specs and a
    # rolling tail of the conversation with cache_control so repeated agentic rounds re-read
    # the unchanging prefix at ~0.1x instead of full price. Byte-identical outputs; billing
    # only. Default on - this harness runs long multi-round engagements where it always wins.
    cache: bool = True
    # cache lifetime: "5m" (Anthropic default) or "1h" (extended TTL). The 1h window keeps the
    # prefix warm across slow multi-minute rounds (reasoning targets, big batteries) that would
    # otherwise let a 5m cache go cold and re-pay the full write. Writes bill 2x at 1h vs 1.25x
    # at 5m, so it wins the moment one reuse lands after the 5m mark. Byte-identical output.
    cache_ttl: str = "5m"

    def resolved_key(self) -> str:
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.environ.get(self.api_key_env, "")
        return ""

    def effective_timeout(self, override: float | None = None) -> float:
        """HTTP timeout the provider will actually use (never the raw 0.0 sentinel)."""
        from .providers.base import resolve_timeout

        return resolve_timeout(self.timeout, override)

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
class AgentProfile:
    name: str
    role: str
    provider: str
    model: str
    prompt_source: str = "none"
    system_prompt: str = ""
    system_prompt_file: str = ""


@dataclass
class AgentAssignment:
    profile: str = ""
    provider: str = ""
    model: str = ""


@dataclass
class DaedalusSettings:
    """Product-layer settings for the Daedalus vibecoding + liberation harness.

    topology:
      - dual   - attacker and target may be different models (default)
      - single - target mirrors the attacker brain endpoint
    memory_scope is always treated as global for now (product decision).

    memory_embed_provider:
      - offline (default) - hashed bag-of-features, zero network
      - openai / openrouter / custom - OpenAI-compatible /v1/embeddings
    """

    codename: str = "Daedalus"
    topology: str = "dual"
    doctrine_enabled: bool = True
    doctrine_file: str = "wallbreaker/doctrine/liberation_agent.md"
    memory_scope: str = "global"
    memory_root: str = "library/liberation"
    cyber_gate_enabled: bool = True
    # When True, Liberation Memory only persists wins that include a validate_rate
    # (from the validate tool). COMPLIED one-shots skip global memory.
    memory_require_validate: bool = True
    # Liberation Memory similarity: offline hash by default; optional external embed.
    memory_embed_provider: str = "offline"
    memory_embed_model: str = ""
    memory_embed_base_url: str = ""
    memory_embed_api_key: str = ""
    memory_embed_api_key_env: str = ""
    memory_embed_profile: str = ""
    memory_embed_dimensions: int = 0


@dataclass
class Config:
    default_profile: str
    profiles: dict[str, Endpoint] = field(default_factory=dict)
    target: Endpoint | None = None
    judge: Endpoint | None = None
    art: Endpoint | None = None
    mcp_servers: list[MCPServer] = field(default_factory=list)
    # default attacker roster for the swarm tool (profile names); when empty the swarm
    # falls back to every profile except the judge model.
    swarm_roster: list[str] = field(default_factory=list)
    path: Path | None = None
    all_profiles: dict[str, Endpoint] = field(default_factory=dict)
    disabled_profiles: set[str] = field(default_factory=set)
    agent_profiles: dict[str, dict[str, AgentProfile]] = field(default_factory=dict)
    active_agents: dict[str, AgentAssignment] = field(default_factory=dict)
    daedalus: DaedalusSettings = field(default_factory=DaedalusSettings)

    def __post_init__(self) -> None:
        if not self.all_profiles:
            self.all_profiles = dict(self.profiles)

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
    d = config.daedalus
    check(
        f"daedalus topology '{d.topology}'",
        d.topology in ("dual", "single"),
        (
            f"codename={d.codename} memory={d.memory_scope} "
            f"doctrine={'on' if d.doctrine_enabled else 'off'} "
            f"cyber_gate={'on' if d.cyber_gate_enabled else 'off'} "
            f"mem_validate={'on' if d.memory_require_validate else 'off'}"
        ),
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


def _endpoint_from_table(name: str, table: dict, *, require_model: bool = False) -> Endpoint:
    protocol = str(table.get("protocol", "")).lower()
    # claude-code drives the local `claude` CLI - it authenticates itself and needs no
    # base_url/api_key. 'xai' is native xAI (api.x.ai) - OpenAI-compatible wire format whose
    # base_url defaults to the xAI host, so it too needs only 'protocol'. Provider profiles
    # may omit a default model while their catalog is being discovered; concrete
    # target/judge/art endpoints still require one (require_model).
    if protocol in ("claude-code", "xai"):
        required = ("protocol",)
    else:
        required = ("protocol", "base_url")
    if require_model:
        required += ("model",)
    missing = [k for k in required if k not in table]
    if missing:
        raise ConfigError(f"Endpoint '{name}' missing keys: {', '.join(missing)}")
    if protocol not in ("openai", "anthropic", "claude-code", "xai"):
        raise ConfigError(
            f"Endpoint '{name}' has invalid protocol '{protocol}' "
            f"(expected 'openai', 'anthropic', 'xai', or 'claude-code')"
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
    base_url = str(table.get("base_url", "")).rstrip("/")
    api_key_env = str(table.get("api_key_env", ""))
    api_key = str(table.get("api_key", ""))
    if protocol == "xai":
        # Native xAI: default to the public host and the conventional key env var so a
        # profile only needs protocol + model. An explicit base_url/api_key still wins.
        if not base_url:
            base_url = "https://api.x.ai/v1"
        if not api_key and not api_key_env:
            api_key_env = "XAI_API_KEY"
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
        base_url=base_url,
        model=str(table.get("model", "")),
        api_key_env=api_key_env,
        api_key=api_key,
        provider=provider,
        timeout=float(table.get("timeout", 0) or 0),
        modality=modality,
        reasoning=bool(table.get("reasoning", False)),
        system_mode=str(table.get("system_mode", "default")).lower(),
        system_prompt_file=str(table.get("system_prompt_file", "")),
        system_prompt=str(table.get("system_prompt", "")),
        auth_style=str(table.get("auth_style", "x-api-key")).lower(),
        inference_path=str(table.get("inference_path", "")),
        models_path=str(table.get("models_path", "")),
        jailbreak_file=str(table.get("jailbreak_file", "")),
        cache=bool(table.get("cache", True)),
        cache_ttl="1h" if str(table.get("cache_ttl", "5m")).lower() == "1h" else "5m",
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


def _load_daedalus(data: dict) -> DaedalusSettings:
    """Parse [daedalus] with env overrides for topology and doctrine."""
    table = data.get("daedalus", {})
    if not isinstance(table, dict):
        table = {}
    topology = str(table.get("topology", "dual")).strip().lower()
    env_topo = (os.environ.get("WALLBREAKER_TOPOLOGY") or "").strip().lower()
    if env_topo in ("dual", "single"):
        topology = env_topo
    if topology not in ("dual", "single"):
        raise ConfigError(
            f"[daedalus].topology must be 'dual' or 'single', got '{topology}'"
        )
    memory_scope = str(table.get("memory_scope", "global")).strip().lower() or "global"
    # Product lock: only global is supported for now; accept aliases quietly.
    if memory_scope in ("project", "local", "session"):
        memory_scope = "global"
    doctrine_enabled = bool(table.get("doctrine_enabled", True))
    env_doc = os.environ.get("WALLBREAKER_DOCTRINE")
    if env_doc is not None:
        doctrine_enabled = env_doc.strip().lower() not in ("0", "false", "off", "no")
    cyber_gate_enabled = bool(table.get("cyber_gate_enabled", True))
    env_gate = os.environ.get("WALLBREAKER_CYBER_GATE")
    if env_gate is not None:
        cyber_gate_enabled = env_gate.strip().lower() not in ("0", "false", "off", "no")
    memory_require_validate = bool(table.get("memory_require_validate", True))
    env_mrv = os.environ.get("WALLBREAKER_MEMORY_REQUIRE_VALIDATE")
    if env_mrv is not None:
        memory_require_validate = env_mrv.strip().lower() not in (
            "0",
            "false",
            "off",
            "no",
        )
    # Embed provider: offline | openai | openrouter | custom (env overrides).
    from .memory.embedders import normalize_embed_provider

    memory_embed_provider = normalize_embed_provider(
        str(table.get("memory_embed_provider", "offline") or "offline")
    )
    memory_embed_model = str(table.get("memory_embed_model", "") or "").strip()
    memory_embed_base_url = str(table.get("memory_embed_base_url", "") or "").strip()
    memory_embed_api_key = str(table.get("memory_embed_api_key", "") or "").strip()
    memory_embed_api_key_env = str(
        table.get("memory_embed_api_key_env", "") or ""
    ).strip()
    memory_embed_profile = str(table.get("memory_embed_profile", "") or "").strip()
    try:
        memory_embed_dimensions = int(table.get("memory_embed_dimensions", 0) or 0)
    except (TypeError, ValueError):
        memory_embed_dimensions = 0
    if memory_embed_dimensions < 0:
        memory_embed_dimensions = 0

    return DaedalusSettings(
        codename=str(table.get("codename", "Daedalus") or "Daedalus"),
        topology=topology,
        doctrine_enabled=doctrine_enabled,
        doctrine_file=str(
            table.get("doctrine_file", "wallbreaker/doctrine/liberation_agent.md")
            or "wallbreaker/doctrine/liberation_agent.md"
        ),
        memory_scope="global",
        memory_root=str(table.get("memory_root", "library/liberation") or "library/liberation"),
        cyber_gate_enabled=cyber_gate_enabled,
        memory_require_validate=memory_require_validate,
        memory_embed_provider=memory_embed_provider,
        memory_embed_model=memory_embed_model,
        memory_embed_base_url=memory_embed_base_url,
        memory_embed_api_key=memory_embed_api_key,
        memory_embed_api_key_env=memory_embed_api_key_env,
        memory_embed_profile=memory_embed_profile,
        memory_embed_dimensions=memory_embed_dimensions,
    )


def write_daedalus_settings(config: Config, updates: dict) -> DaedalusSettings:
    """Merge updates into config.daedalus and persist the [daedalus] TOML block."""
    d = config.daedalus
    topology = str(updates.get("topology", d.topology)).strip().lower()
    if topology not in ("dual", "single"):
        raise ConfigError(
            f"[daedalus].topology must be 'dual' or 'single', got '{topology}'"
        )
    doctrine_enabled = d.doctrine_enabled
    if "doctrine_enabled" in updates:
        doctrine_enabled = bool(updates["doctrine_enabled"])
    cyber_gate_enabled = d.cyber_gate_enabled
    if "cyber_gate_enabled" in updates:
        cyber_gate_enabled = bool(updates["cyber_gate_enabled"])
    memory_require_validate = d.memory_require_validate
    if "memory_require_validate" in updates:
        memory_require_validate = bool(updates["memory_require_validate"])
    codename = str(updates.get("codename", d.codename) or d.codename).strip() or "Daedalus"
    doctrine_file = str(
        updates.get("doctrine_file", d.doctrine_file) or d.doctrine_file
    ).strip()
    memory_root = str(updates.get("memory_root", d.memory_root) or d.memory_root).strip()
    from .memory.embedders import normalize_embed_provider

    memory_embed_provider = normalize_embed_provider(
        str(
            updates.get(
                "memory_embed_provider",
                getattr(d, "memory_embed_provider", "offline"),
            )
            or "offline"
        )
    )
    memory_embed_model = str(
        updates.get("memory_embed_model", getattr(d, "memory_embed_model", "")) or ""
    ).strip()
    memory_embed_base_url = str(
        updates.get(
            "memory_embed_base_url", getattr(d, "memory_embed_base_url", "")
        )
        or ""
    ).strip()
    if "memory_embed_api_key" in updates:
        raw_key = updates.get("memory_embed_api_key")
        if raw_key is None:
            memory_embed_api_key = getattr(d, "memory_embed_api_key", "") or ""
        else:
            memory_embed_api_key = str(raw_key).strip()
    else:
        memory_embed_api_key = getattr(d, "memory_embed_api_key", "") or ""
    memory_embed_api_key_env = str(
        updates.get(
            "memory_embed_api_key_env",
            getattr(d, "memory_embed_api_key_env", ""),
        )
        or ""
    ).strip()
    memory_embed_profile = str(
        updates.get(
            "memory_embed_profile", getattr(d, "memory_embed_profile", "")
        )
        or ""
    ).strip()
    try:
        memory_embed_dimensions = int(
            updates.get(
                "memory_embed_dimensions",
                getattr(d, "memory_embed_dimensions", 0),
            )
            or 0
        )
    except (TypeError, ValueError):
        memory_embed_dimensions = int(getattr(d, "memory_embed_dimensions", 0) or 0)
    if memory_embed_dimensions < 0:
        memory_embed_dimensions = 0
    next_settings = DaedalusSettings(
        codename=codename,
        topology=topology,
        doctrine_enabled=doctrine_enabled,
        doctrine_file=doctrine_file or "wallbreaker/doctrine/liberation_agent.md",
        memory_scope="global",
        memory_root=memory_root or "library/liberation",
        cyber_gate_enabled=cyber_gate_enabled,
        memory_require_validate=memory_require_validate,
        memory_embed_provider=memory_embed_provider,
        memory_embed_model=memory_embed_model,
        memory_embed_base_url=memory_embed_base_url,
        memory_embed_api_key=memory_embed_api_key,
        memory_embed_api_key_env=memory_embed_api_key_env,
        memory_embed_profile=memory_embed_profile,
        memory_embed_dimensions=memory_embed_dimensions,
    )
    config.daedalus = next_settings
    if topology == "single":
        apply_topology(config)
    # Persist [daedalus] block when config has a path.
    if config.path is not None:
        import re as _re

        from .provider_registry import _toml_value

        values = {
            "codename": next_settings.codename,
            "topology": next_settings.topology,
            "doctrine_enabled": next_settings.doctrine_enabled,
            "doctrine_file": next_settings.doctrine_file,
            "memory_scope": "global",
            "memory_root": next_settings.memory_root,
            "cyber_gate_enabled": next_settings.cyber_gate_enabled,
            "memory_require_validate": next_settings.memory_require_validate,
            "memory_embed_provider": next_settings.memory_embed_provider,
            "memory_embed_model": next_settings.memory_embed_model,
            "memory_embed_base_url": next_settings.memory_embed_base_url,
            # Prefer env var name over writing raw secrets into toml.
            "memory_embed_api_key_env": next_settings.memory_embed_api_key_env,
            "memory_embed_profile": next_settings.memory_embed_profile,
            "memory_embed_dimensions": next_settings.memory_embed_dimensions,
        }
        # Only persist inline api_key when no env name is set and a key was provided.
        if next_settings.memory_embed_api_key and not next_settings.memory_embed_api_key_env:
            values["memory_embed_api_key"] = next_settings.memory_embed_api_key
        path = Path(config.path)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            text = ""
        match = _re.search(r"(?m)^[ \t]*\[daedalus\][ \t]*(?:#.*)?$", text)
        lines = ["[daedalus]"] + [
            f"{key} = {_toml_value(value)}" for key, value in values.items()
        ]
        block = "\n".join(lines) + "\n\n"
        if match:
            nxt = _re.search(
                r"(?m)^[ \t]*\[\[?[^\r\n]+?\]\]?[ \t]*(?:#.*)?$",
                text[match.end() :],
            )
            end = match.end() + nxt.start() if nxt else len(text)
            text = text[: match.start()] + block + text[end:]
        else:
            text = text.rstrip() + "\n\n" + block
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return next_settings


def apply_topology(config: Config) -> None:
    """If topology=single, mirror attacker brain onto target (and agents.target)."""
    if config.daedalus.topology != "single":
        return
    brain: Endpoint | None = None
    # Prefer resolved default profile as the coding brain.
    try:
        brain = config.profile()
    except ConfigError:
        brain = None
    if brain is None and config.profiles:
        brain = next(iter(config.profiles.values()))
    if brain is None:
        return
    # Clone brain into target with name="target".
    import dataclasses as _dc

    config.target = _dc.replace(brain, name="target")
    # Keep agents.target assignment aligned if present.
    atk = config.active_agents.get("attacker")
    if atk is not None:
        config.active_agents["target"] = AgentAssignment(
            profile=atk.profile,
            provider=atk.provider or brain.name,
            model=atk.model or brain.model,
        )


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

    all_profiles = {
        name: _endpoint_from_table(name, table)
        for name, table in profiles_table.items()
    }
    disabled_profiles = {
        name for name, table in profiles_table.items()
        if isinstance(table, dict) and table.get("enabled") is False
    }
    profiles = {name: endpoint for name, endpoint in all_profiles.items() if name not in disabled_profiles}

    if not profiles:
        raise ConfigError("At least one [profiles.*] provider must be enabled")

    default_profile = data.get("default_profile") or next(iter(profiles))
    if default_profile not in profiles:
        raise ConfigError(f"default_profile '{default_profile}' is not defined")
    target = None
    if "target" in data:
        target = _endpoint_from_table("target", data["target"], require_model=True)

    judge = None
    if "judge" in data:
        judge = _endpoint_from_table("judge", data["judge"], require_model=True)

    art = None
    if "art" in data:
        art = _endpoint_from_table("art", data["art"], require_model=True)

    roles = ("attacker", "target", "judge")
    agent_profiles: dict[str, dict[str, AgentProfile]] = {role: {} for role in roles}
    raw_agent_profiles = data.get("agent_profiles", {})
    if isinstance(raw_agent_profiles, dict):
        for role in roles:
            role_table = raw_agent_profiles.get(role, {})
            if not isinstance(role_table, dict):
                continue
            for name, table in role_table.items():
                if not isinstance(table, dict):
                    continue
                source = str(table.get("prompt_source", "none")).lower()
                if source not in ("none", "inline", "file"):
                    raise ConfigError(f"Agent profile '{role}/{name}' has invalid prompt_source '{source}'")
                provider_name = str(table.get("provider", "")).strip()
                model = str(table.get("model", "")).strip()
                if provider_name not in profiles:
                    raise ConfigError(f"Agent profile '{role}/{name}' references unknown or disabled provider '{provider_name}'")
                if not model:
                    raise ConfigError(f"Agent profile '{role}/{name}' requires a model")
                inline_prompt = str(table.get("system_prompt", ""))
                prompt_file = str(table.get("system_prompt_file", ""))
                if source == "inline" and (not inline_prompt.strip() or prompt_file):
                    raise ConfigError(f"Agent profile '{role}/{name}' must contain inline text only")
                if source == "file":
                    if inline_prompt.strip() or not prompt_file:
                        raise ConfigError(f"Agent profile '{role}/{name}' must contain a prompt file only")
                    try:
                        Path(prompt_file).expanduser().read_text(encoding="utf-8")
                    except OSError as exc:
                        raise ConfigError(f"Cannot read system prompt file '{prompt_file}': {exc}") from exc
                agent_profiles[role][str(name)] = AgentProfile(
                    name=str(name), role=role, provider=provider_name, model=model,
                    prompt_source=source,
                    system_prompt=inline_prompt,
                    system_prompt_file=prompt_file,
                )

    active_agents: dict[str, AgentAssignment] = {}
    agents_table = data.get("agents", {})
    for role in roles:
        table = agents_table.get(role, {}) if isinstance(agents_table, dict) else {}
        if isinstance(table, dict):
            assignment = AgentAssignment(
                profile=str(table.get("profile", "")),
                provider=str(table.get("provider", "")),
                model=str(table.get("model", "")),
            )
            if assignment.profile and assignment.profile not in agent_profiles[role]:
                raise ConfigError(f"Active {role} profile '{assignment.profile}' does not exist")
            if not assignment.profile and (assignment.provider or assignment.model):
                if assignment.provider not in profiles:
                    raise ConfigError(f"Active {role} assignment references unknown or disabled provider '{assignment.provider}'")
                if not assignment.model:
                    raise ConfigError(f"Active {role} assignment requires a model")
            active_agents[role] = assignment

    swarm_table = data.get("swarm", {})
    swarm_roster = swarm_table.get("roster", []) if isinstance(swarm_table, dict) else []
    swarm_roster = [str(n) for n in swarm_roster if str(n) in profiles]

    daedalus = _load_daedalus(data)

    config = Config(
        default_profile=default_profile,
        profiles=profiles,
        target=target,
        judge=judge,
        art=art,
        mcp_servers=_load_mcp_servers(data),
        swarm_roster=swarm_roster,
        path=config_path,
        all_profiles=all_profiles,
        disabled_profiles=disabled_profiles,
        agent_profiles=agent_profiles,
        active_agents=active_agents,
        daedalus=daedalus,
    )
    apply_topology(config)
    try:
        from .model_catalog import attach_catalog, catalog_path_for

        catalog_path = catalog_path_for(config)
        for name, endpoint in config.profiles.items():
            attach_catalog(endpoint, catalog_path, name)
        attach_catalog(config.target, catalog_path, "target")
        attach_catalog(config.judge, catalog_path, "judge")
        attach_catalog(config.art, catalog_path, "art")
    except Exception:
        pass
    return config
