"""External + offline embedders for Liberation Memory REPLAY.

Default path stays fully offline (hashed bag-of-features in liberation_store).
Optional OpenAI-compatible ``/v1/embeddings`` providers plug in through
``build_embed_fn(config)`` -> Callable[[str], list[float]] | None.

Design:
  - offline / empty / missing key  -> None (store uses hashed embed)
  - openai / openrouter / custom   -> sync httpx POST, process-local LRU cache
  - any network/HTTP failure       -> raise; hybrid_similarity catches and
    falls back to token/hash so REPLAY never hard-fails on embed blips
  - WALLBREAKER_MEMORY_EMBED=0     -> always None (kills hashed + external)
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections import OrderedDict
from typing import Any, Callable, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from ..config import Config, DaedalusSettings, Endpoint

# Sensible public defaults. Custom base_url always wins.
_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "text-embedding-3-small",
        "api_key_env": "OPENAI_API_KEY",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/text-embedding-3-small",
        "api_key_env": "OPENROUTER_API_KEY",
    },
}

# Keep small: REPLAY ranks a few dozen catalog rows, not a corpus.
_DEFAULT_CACHE = 512
_DEFAULT_TIMEOUT = 20.0


def normalize_embed_provider(raw: str | None) -> str:
    """Map config/env aliases to a canonical provider id."""
    name = (raw or "offline").strip().lower()
    if name in ("", "off", "none", "hash", "hashed", "local", "offline"):
        return "offline"
    if name in ("openai", "oai"):
        return "openai"
    if name in ("openrouter", "or"):
        return "openrouter"
    if name in ("custom", "http", "openai-compatible", "compatible"):
        return "custom"
    # bare profile-style names still treated as custom endpoint labels
    return name


class LruEmbedCache:
    """Thread-safe string -> vector cache (process local)."""

    def __init__(self, maxsize: int = _DEFAULT_CACHE) -> None:
        self.maxsize = max(1, int(maxsize))
        self._data: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> list[float] | None:
        with self._lock:
            vec = self._data.get(key)
            if vec is None:
                return None
            self._data.move_to_end(key)
            return list(vec)

    def put(self, key: str, vec: list[float]) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = list(vec)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


def _cache_key(text: str, model: str) -> str:
    h = hashlib.sha1(f"{model}\0{text}".encode("utf-8")).hexdigest()
    return h


class OpenAICompatibleEmbedder:
    """Minimal OpenAI-compatible embeddings client (sync, cached)."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        dimensions: int = 0,
        timeout: float = _DEFAULT_TIMEOUT,
        cache_size: int = _DEFAULT_CACHE,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.model = model or "text-embedding-3-small"
        self.api_key = api_key or ""
        self.dimensions = int(dimensions or 0)
        self.timeout = float(timeout) if timeout and timeout > 0 else _DEFAULT_TIMEOUT
        self._cache = LruEmbedCache(cache_size)
        self._extra_headers = dict(extra_headers or {})

    @property
    def embeddings_url(self) -> str:
        base = self.base_url
        if base.endswith("/embeddings"):
            return base
        return f"{base}/embeddings"

    def embed(self, text: str) -> list[float]:
        raw = text or ""
        key = _cache_key(raw, self.model)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        if not self.api_key:
            raise RuntimeError("embedder has no api_key")
        if not self.base_url:
            raise RuntimeError("embedder has no base_url")
        body: dict[str, Any] = {"model": self.model, "input": raw}
        if self.dimensions > 0:
            body["dimensions"] = self.dimensions
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self._extra_headers,
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self.embeddings_url, json=body, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
        vec = _extract_embedding(payload)
        if not vec:
            raise RuntimeError("embed response missing embedding vector")
        self._cache.put(key, vec)
        return list(vec)

    def __call__(self, text: str) -> list[float]:
        return self.embed(text)


def _extract_embedding(payload: Any) -> list[float]:
    """Accept common OpenAI-compatible embedding response shapes."""
    if isinstance(payload, list) and payload and isinstance(payload[0], (int, float)):
        return [float(x) for x in payload]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            emb = first.get("embedding") or first.get("vector")
            if isinstance(emb, list):
                return [float(x) for x in emb]
        if isinstance(first, list):
            return [float(x) for x in first]
    emb = payload.get("embedding")
    if isinstance(emb, list):
        return [float(x) for x in emb]
    return []


def _endpoint_from_profile(config: "Config", name: str) -> "Endpoint | None":
    profiles = getattr(config, "profiles", None) or {}
    if name in profiles:
        return profiles[name]
    # case-insensitive fallback
    low = name.lower()
    for key, ep in profiles.items():
        if str(key).lower() == low:
            return ep
    return None


def resolve_embed_settings(
    config: "Config | None" = None,
    daedalus: "DaedalusSettings | None" = None,
) -> dict[str, Any]:
    """Resolve effective embed provider settings (config + env)."""
    d = daedalus
    if d is None and config is not None:
        d = getattr(config, "daedalus", None)

    provider = normalize_embed_provider(
        getattr(d, "memory_embed_provider", None) if d else None
    )
    env_prov = os.environ.get("WALLBREAKER_MEMORY_EMBED_PROVIDER")
    if env_prov is not None and env_prov.strip():
        provider = normalize_embed_provider(env_prov)

    model = str(getattr(d, "memory_embed_model", "") or "") if d else ""
    base_url = str(getattr(d, "memory_embed_base_url", "") or "") if d else ""
    api_key = str(getattr(d, "memory_embed_api_key", "") or "") if d else ""
    api_key_env = str(getattr(d, "memory_embed_api_key_env", "") or "") if d else ""
    profile = str(getattr(d, "memory_embed_profile", "") or "") if d else ""
    dimensions = int(getattr(d, "memory_embed_dimensions", 0) or 0) if d else 0

    env_model = os.environ.get("WALLBREAKER_MEMORY_EMBED_MODEL")
    if env_model and env_model.strip():
        model = env_model.strip()
    env_base = os.environ.get("WALLBREAKER_MEMORY_EMBED_BASE_URL")
    if env_base and env_base.strip():
        base_url = env_base.strip()
    env_key = os.environ.get("WALLBREAKER_MEMORY_EMBED_API_KEY")
    if env_key and env_key.strip():
        api_key = env_key.strip()
    env_key_env = os.environ.get("WALLBREAKER_MEMORY_EMBED_API_KEY_ENV")
    if env_key_env and env_key_env.strip():
        api_key_env = env_key_env.strip()
    env_profile = os.environ.get("WALLBREAKER_MEMORY_EMBED_PROFILE")
    if env_profile and env_profile.strip():
        profile = env_profile.strip()
    env_dim = os.environ.get("WALLBREAKER_MEMORY_EMBED_DIMENSIONS")
    if env_dim and env_dim.strip().isdigit():
        dimensions = int(env_dim.strip())

    defaults = _PROVIDER_DEFAULTS.get(provider, {})
    if not model:
        model = defaults.get("model", "text-embedding-3-small")
    if not base_url:
        base_url = defaults.get("base_url", "")
    if not api_key_env:
        api_key_env = defaults.get("api_key_env", "")

    # Borrow connection details from a named profile when asked.
    if profile and config is not None:
        ep = _endpoint_from_profile(config, profile)
        if ep is not None:
            if not base_url:
                base_url = (ep.base_url or "").rstrip("/")
            if not api_key:
                try:
                    api_key = ep.resolved_key()
                except Exception:
                    api_key = ep.api_key or ""
            if not api_key_env and ep.api_key_env:
                api_key_env = ep.api_key_env
            # If profile model looks embedding-ish keep it; else keep embed model.
            mid = (ep.model or "").lower()
            if "embed" in mid and not str(getattr(d, "memory_embed_model", "") or ""):
                model = ep.model

    if not api_key and api_key_env:
        api_key = os.environ.get(api_key_env, "") or ""

    return {
        "provider": provider,
        "model": model,
        "base_url": (base_url or "").rstrip("/"),
        "api_key": api_key or "",
        "api_key_env": api_key_env or "",
        "profile": profile or "",
        "dimensions": int(dimensions or 0),
    }


def build_embedder(
    config: "Config | None" = None,
    *,
    daedalus: "DaedalusSettings | None" = None,
    timeout: float = _DEFAULT_TIMEOUT,
    cache_size: int = _DEFAULT_CACHE,
) -> OpenAICompatibleEmbedder | None:
    """Construct an external embedder, or None for offline/hashed mode."""
    from .liberation_store import memory_embed_enabled

    if not memory_embed_enabled():
        return None
    settings = resolve_embed_settings(config, daedalus=daedalus)
    provider = settings["provider"]
    if provider == "offline":
        return None
    if not settings["api_key"] or not settings["base_url"]:
        return None
    extra: dict[str, str] = {}
    if provider == "openrouter" or "openrouter.ai" in settings["base_url"]:
        # OpenRouter recommends these; harmless if ignored.
        extra["HTTP-Referer"] = "https://github.com/wallbreaker"
        extra["X-Title"] = "wallbreaker-liberation-memory"
    return OpenAICompatibleEmbedder(
        base_url=settings["base_url"],
        model=settings["model"],
        api_key=settings["api_key"],
        dimensions=settings["dimensions"],
        timeout=timeout,
        cache_size=cache_size,
        extra_headers=extra,
    )


def build_embed_fn(
    config: "Config | None" = None,
    *,
    daedalus: "DaedalusSettings | None" = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> Callable[[str], list[float]] | None:
    """Return a sync ``text -> vector`` callable for LiberationStore, or None.

    None means: use offline hashed embeddings inside hybrid_similarity.
    """
    embedder = build_embedder(config, daedalus=daedalus, timeout=timeout)
    if embedder is None:
        return None
    return embedder


def embed_status(config: "Config | None" = None) -> dict[str, Any]:
    """Operator-facing status for /memory and dashboard (no secrets)."""
    from .liberation_store import memory_embed_enabled

    settings = resolve_embed_settings(config)
    enabled = memory_embed_enabled()
    ready = bool(
        enabled
        and settings["provider"] != "offline"
        and settings["api_key"]
        and settings["base_url"]
    )
    return {
        "enabled": enabled,
        "provider": settings["provider"],
        "model": settings["model"],
        "base_url": settings["base_url"],
        "profile": settings["profile"],
        "dimensions": settings["dimensions"],
        "api_key_env": settings["api_key_env"],
        "has_api_key": bool(settings["api_key"]),
        "ready": ready,
        "mode": "external" if ready else ("offline-hash" if enabled else "disabled"),
    }
