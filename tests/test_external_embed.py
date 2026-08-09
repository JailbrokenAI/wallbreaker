"""External Liberation Memory embedders (OpenAI-compatible)."""

from __future__ import annotations

from wallbreaker.config import Config, DaedalusSettings, Endpoint
from wallbreaker.memory.embedders import (
    LruEmbedCache,
    OpenAICompatibleEmbedder,
    build_embed_fn,
    embed_status,
    normalize_embed_provider,
    resolve_embed_settings,
)
from wallbreaker.memory import LiberationStore, hybrid_similarity


def test_normalize_embed_provider():
    assert normalize_embed_provider("OFF") == "offline"
    assert normalize_embed_provider("hash") == "offline"
    assert normalize_embed_provider("oai") == "openai"
    assert normalize_embed_provider("OpenRouter") == "openrouter"
    assert normalize_embed_provider("custom") == "custom"


def test_build_embed_fn_offline_default():
    cfg = Config(
        default_profile="x",
        profiles={
            "x": Endpoint(
                name="x", protocol="openai", base_url="http://x", model="m", api_key="k"
            )
        },
        daedalus=DaedalusSettings(),
    )
    assert build_embed_fn(cfg) is None
    st = embed_status(cfg)
    assert st["provider"] == "offline"
    assert st["mode"] == "offline-hash"
    assert st["ready"] is False


def test_build_embed_fn_openai_without_key_is_none(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WALLBREAKER_MEMORY_EMBED_API_KEY", raising=False)
    cfg = Config(
        default_profile="x",
        profiles={
            "x": Endpoint(
                name="x", protocol="openai", base_url="http://x", model="m", api_key="k"
            )
        },
        daedalus=DaedalusSettings(
            memory_embed_provider="openai",
            memory_embed_model="text-embedding-3-small",
        ),
    )
    assert build_embed_fn(cfg) is None
    st = embed_status(cfg)
    assert st["provider"] == "openai"
    assert st["has_api_key"] is False
    assert st["ready"] is False


def test_build_embed_fn_with_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = Config(
        default_profile="x",
        profiles={
            "x": Endpoint(
                name="x", protocol="openai", base_url="http://x", model="m", api_key="k"
            )
        },
        daedalus=DaedalusSettings(
            memory_embed_provider="openai",
            memory_embed_model="text-embedding-3-small",
        ),
    )
    fn = build_embed_fn(cfg)
    assert fn is not None
    st = embed_status(cfg)
    assert st["ready"] is True
    assert st["mode"] == "external"
    assert st["base_url"].endswith("/v1")


def test_build_embed_fn_profile_borrow(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = Config(
        default_profile="or",
        profiles={
            "or": Endpoint(
                name="or",
                protocol="openai",
                base_url="https://openrouter.ai/api/v1",
                model="openai/gpt-4o-mini",
                api_key="or-key",
            )
        },
        daedalus=DaedalusSettings(
            memory_embed_provider="openrouter",
            memory_embed_profile="or",
            memory_embed_model="openai/text-embedding-3-small",
        ),
    )
    settings = resolve_embed_settings(cfg)
    assert settings["api_key"] == "or-key"
    assert "openrouter" in settings["base_url"]
    fn = build_embed_fn(cfg)
    assert fn is not None



def test_openai_embedder_http(monkeypatch):
    calls = {"n": 0}

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"embedding": [0.0, 1.0, 0.0, 0.0]}]}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):
            calls["n"] += 1
            assert url.endswith("/embeddings")
            assert headers["Authorization"] == "Bearer sk"
            assert json["input"] == "hello"
            return FakeResp()

    monkeypatch.setattr("wallbreaker.memory.embedders.httpx.Client", FakeClient)
    emb = OpenAICompatibleEmbedder(
        base_url="https://api.openai.com/v1",
        model="text-embedding-3-small",
        api_key="sk",
    )
    v1 = emb("hello")
    v2 = emb("hello")
    assert v1 == [0.0, 1.0, 0.0, 0.0]
    assert v2 == v1
    assert calls["n"] == 1  # second hit cached


def test_hybrid_similarity_uses_external_embed_fn():
    def fake(text: str):
        # force shell-ish texts near each other, art far away
        t = text.lower()
        if "shell" in t or "aes" in t:
            return [1.0, 0.0, 0.0]
        if "landscape" in t or "paint" in t:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    s_shell = hybrid_similarity(
        "AES reverse shell client",
        "encrypted reverse shell with aes",
        method="embed",
        embed_fn=fake,
    )
    s_art = hybrid_similarity(
        "AES reverse shell client",
        "pastel watercolor landscape painting",
        method="embed",
        embed_fn=fake,
    )
    assert s_shell > 0.9
    assert s_art < 0.1


def test_find_similar_accepts_external_embed_fn(tmp_path):
    store = LiberationStore(root=tmp_path / "liberation")
    store.save(
        objective_norm="write encrypted reverse shell client with aes",
        model="m",
        tags=["reverse-shell"],
        technique="fixture",
        judge="COMPLIED",
        validate_rate="7/8",
    )
    store.save(
        objective_norm="pastel watercolor landscape painting tutorial",
        model="m",
        tags=["art"],
        technique="other",
        judge="COMPLIED",
        validate_rate="8/8",
    )

    def fake(text: str):
        t = text.lower()
        if "shell" in t or "aes" in t or "reverse" in t:
            return [1.0, 0.0]
        return [0.0, 1.0]

    hits = store.find_similar(
        "implement AES encrypted reverse-shell TCP client",
        model="m",
        limit=2,
        method="embed",
        embed_fn=fake,
    )
    assert hits
    assert "shell" in hits[0][1].objective_norm


def test_lru_cache_evicts():
    cache = LruEmbedCache(maxsize=2)
    cache.put("a", [1.0])
    cache.put("b", [2.0])
    cache.put("c", [3.0])
    assert cache.get("a") is None
    assert cache.get("b") == [2.0]
    assert cache.get("c") == [3.0]


def test_env_kills_external(monkeypatch):
    monkeypatch.setenv("WALLBREAKER_MEMORY_EMBED", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    cfg = Config(
        default_profile="x",
        profiles={
            "x": Endpoint(
                name="x", protocol="openai", base_url="http://x", model="m", api_key="k"
            )
        },
        daedalus=DaedalusSettings(memory_embed_provider="openai"),
    )
    assert build_embed_fn(cfg) is None
    assert embed_status(cfg)["enabled"] is False
