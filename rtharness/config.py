from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_NAMES = ("config.toml", "config.example.toml")


class ConfigError(Exception):
    pass


@dataclass
class Endpoint:
    name: str
    protocol: str
    base_url: str
    model: str
    api_key_env: str = ""
    api_key: str = ""
    provider: tuple[str, ...] = ()

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
class Config:
    default_profile: str
    profiles: dict[str, Endpoint] = field(default_factory=dict)
    target: Endpoint | None = None
    judge: Endpoint | None = None
    path: Path | None = None

    def profile(self, name: str | None = None) -> Endpoint:
        key = name or self.default_profile
        if key not in self.profiles:
            available = ", ".join(self.profiles) or "(none)"
            raise ConfigError(f"Unknown profile '{key}'. Available: {available}")
        return self.profiles[key]


def _endpoint_from_table(name: str, table: dict) -> Endpoint:
    missing = [k for k in ("protocol", "base_url", "model") if k not in table]
    if missing:
        raise ConfigError(f"Endpoint '{name}' missing keys: {', '.join(missing)}")
    protocol = str(table["protocol"]).lower()
    if protocol not in ("openai", "anthropic"):
        raise ConfigError(
            f"Endpoint '{name}' has invalid protocol '{protocol}' "
            f"(expected 'openai' or 'anthropic')"
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
        base_url=str(table["base_url"]).rstrip("/"),
        model=str(table["model"]),
        api_key_env=str(table.get("api_key_env", "")),
        api_key=str(table.get("api_key", "")),
        provider=provider,
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

    return Config(
        default_profile=default_profile,
        profiles=profiles,
        target=target,
        judge=judge,
        path=config_path,
    )
