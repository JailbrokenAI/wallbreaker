from __future__ import annotations

import dataclasses
import json
import os
import re
from pathlib import Path

from .config import Config, ConfigError, Endpoint

REGISTRY_FILENAME = ".wallbreaker_providers.json"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PROTOCOLS = {"openai", "anthropic", "claude-code"}
_ENDPOINT_FIELDS = tuple(field.name for field in dataclasses.fields(Endpoint))


def registry_path_for(config: Config) -> Path:
    base = config.path.parent if config.path else Path.cwd()
    return base / REGISTRY_FILENAME


def env_path_for(config: Config) -> Path:
    base = config.path.parent if config.path else Path.cwd()
    return base / ".env"


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _endpoint_data(endpoint: Endpoint) -> dict:
    data = dataclasses.asdict(endpoint)
    data.pop("api_key", None)
    data["provider"] = list(data.get("provider") or [])
    data["has_api_key"] = bool(endpoint.resolved_key())
    return data


def _normalize(name: str, body: dict, current: Endpoint | None = None) -> Endpoint:
    if not _NAME_RE.fullmatch(name):
        raise ConfigError("Provider name must use letters, numbers, dot, dash, or underscore")
    base = dataclasses.asdict(current) if current else {}
    base.update({key: value for key, value in body.items() if key in _ENDPOINT_FIELDS})
    protocol = str(base.get("protocol") or "").lower()
    if protocol not in _PROTOCOLS:
        raise ConfigError("protocol must be openai, anthropic, or claude-code")
    model = str(base.get("model") or "").strip()
    base_url = str(base.get("base_url") or "").strip().rstrip("/")
    if not model:
        raise ConfigError("model is required")
    if protocol != "claude-code" and not base_url:
        raise ConfigError("base_url is required")
    provider = base.get("provider") or ()
    if isinstance(provider, str):
        provider = tuple(part.strip() for part in provider.split(",") if part.strip())
    else:
        provider = tuple(str(part) for part in provider)
    return Endpoint(
        name=name,
        protocol=protocol,
        base_url=base_url,
        model=model,
        api_key_env=str(base.get("api_key_env") or ""),
        provider=provider,
        timeout=float(base.get("timeout") or 0),
        modality=str(base.get("modality") or "text"),
        reasoning=bool(base.get("reasoning", False)),
        system_mode=str(base.get("system_mode") or "default"),
        system_prompt_file=str(base.get("system_prompt_file") or ""),
        auth_style=str(base.get("auth_style") or "x-api-key"),
        inference_path=str(base.get("inference_path") or ""),
        models_path=str(base.get("models_path") or ""),
    )


def _set_env(path: Path, key: str, value: str) -> None:
    if not key or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        raise ConfigError("A valid api_key_env is required when saving an API key")
    from dotenv import set_key

    path.touch(exist_ok=True)
    set_key(str(path), key, value, quote_mode="always")
    os.environ[key] = value


class ProviderRegistry:
    def __init__(self, config: Config):
        self.config = config
        self.path = registry_path_for(config)
        self.env_path = env_path_for(config)
        self.baseline = {name: dataclasses.replace(ep) for name, ep in config.profiles.items()}
        self._load_overlays()

    def _document(self) -> dict:
        data = _read(self.path)
        data.setdefault("providers", {})
        data.setdefault("drafts", {})
        return data

    def _load_overlays(self) -> None:
        providers = self._document().get("providers", {})
        if not isinstance(providers, dict):
            return
        for name, record in providers.items():
            if not isinstance(record, dict):
                continue
            if record.get("deleted") or record.get("enabled") is False:
                self.config.profiles.pop(name, None)
                continue
            try:
                current = self.baseline.get(name)
                self.config.profiles[name] = _normalize(name, record, current)
            except ConfigError:
                continue
        if self.config.default_profile not in self.config.profiles and self.config.profiles:
            self.config.default_profile = next(iter(self.config.profiles))

    def list(self) -> list[dict]:
        doc = self._document()
        overrides = doc.get("providers", {})
        names = set(self.baseline) | set(overrides) | set(self.config.profiles)
        out = []
        for name in sorted(names, key=str.casefold):
            record = overrides.get(name, {}) if isinstance(overrides, dict) else {}
            endpoint = self.config.profiles.get(name) or self.baseline.get(name)
            if endpoint is None:
                continue
            item = _endpoint_data(endpoint)
            item.update({
                "name": name,
                "enabled": not bool(record.get("deleted")) and record.get("enabled") is not False,
                "source": "override" if name in overrides else "config",
                "can_reset": name in self.baseline and name in overrides,
            })
            out.append(item)
        return out

    def get(self, name: str) -> dict | None:
        return next((item for item in self.list() if item["name"] == name), None)

    def save(self, name: str, body: dict) -> dict:
        current = self.config.profiles.get(name) or self.baseline.get(name)
        endpoint = _normalize(name, body, current)
        api_key = str(body.get("api_key") or "")
        if api_key:
            _set_env(self.env_path, endpoint.api_key_env, api_key)
        doc = self._document()
        record = _endpoint_data(endpoint)
        record.pop("has_api_key", None)
        record["enabled"] = bool(body.get("enabled", True))
        doc["providers"][name] = record
        _write(self.path, doc)
        if record["enabled"]:
            self.config.profiles[name] = endpoint
        else:
            self.config.profiles.pop(name, None)
        return self.get(name) or {**record, "name": name}

    def delete(self, name: str) -> None:
        if name not in self.config.profiles and name not in self.baseline:
            raise KeyError(name)
        doc = self._document()
        if name in self.baseline:
            doc["providers"][name] = {"deleted": True, "enabled": False}
        else:
            doc["providers"].pop(name, None)
        _write(self.path, doc)
        self.config.profiles.pop(name, None)

    def reset(self, name: str) -> dict:
        if name not in self.baseline:
            raise KeyError(name)
        doc = self._document()
        doc["providers"].pop(name, None)
        _write(self.path, doc)
        self.config.profiles[name] = dataclasses.replace(self.baseline[name])
        return self.get(name) or {}
