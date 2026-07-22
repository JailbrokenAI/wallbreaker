import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from wallbreaker.agent.messages import Message, StopEvent, TextDelta
from wallbreaker.config import Config, Endpoint
from wallbreaker.dashboard.server import create_app
from wallbreaker.model_catalog import ModelCatalog, attach_catalog
from wallbreaker.providers.base import Provider


def _config(tmp_path):
    return Config(
        default_profile="router",
        profiles={"router": Endpoint("router", "openai", "https://router.example/v1", "configured-model")},
        path=tmp_path / "config.toml",
    )


def test_catalog_persists_manual_and_configured_models(tmp_path):
    cfg = _config(tmp_path)
    client = TestClient(create_app(config=cfg, sessions_dir=tmp_path / "sessions", require_auth=False))
    initial = client.get("/api/providers/router/models").json()
    assert initial["models"] == ["configured-model"]
    added = client.post("/api/providers/router/models", json={"model": "pasted-model"})
    assert added.status_code == 200

    reopened = ModelCatalog(tmp_path / ".wallbreaker_models.sqlite3")
    entries = reopened.list("router")
    assert {item["model_id"] for item in entries} == {"configured-model", "pasted-model"}
    assert next(item for item in entries if item["model_id"] == "pasted-model")["source"] == "manual"


@pytest.mark.asyncio
async def test_successful_completion_learns_model(tmp_path):
    endpoint = Endpoint("ep", "openai", "https://example.test/v1", "live-model")
    attach_catalog(endpoint, tmp_path / "models.sqlite3", "provider-one")

    class FakeProvider(Provider):
        async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
            yield TextDelta("worked")
            yield StopEvent("end_turn")

    text = await FakeProvider(endpoint).complete([Message(role="user", content=[])])
    assert text == "worked"
    entries = ModelCatalog(tmp_path / "models.sqlite3").list("provider-one")
    assert entries[0]["model_id"] == "live-model"
    assert entries[0]["source"] == "inference"


def test_refresh_merges_remote_models(monkeypatch, tmp_path):
    cfg = _config(tmp_path)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "remote-b"}, {"id": "remote-a"}]}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers):
            return Response()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    client = TestClient(create_app(config=cfg, sessions_dir=tmp_path / "sessions", require_auth=False))
    result = client.post("/api/providers/router/models/refresh").json()
    assert result["fetched"] is True
    assert result["models"] == ["configured-model", "remote-a", "remote-b"]


def test_normal_model_lookup_fetches_provider_only_once(monkeypatch, tmp_path):
    cfg = _config(tmp_path)
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "remote-model"}]}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers):
            calls.append(url)
            return Response()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    client = TestClient(create_app(config=cfg, sessions_dir=tmp_path / "sessions", require_auth=False))
    first = client.get("/api/models", params={"profile": "router"}).json()
    second = client.get("/api/models", params={"profile": "router"}).json()

    assert calls == ["https://router.example/v1/models"]
    assert first.get("cached") is not True
    assert second["cached"] is True
    assert second["models"] == ["configured-model", "remote-model"]
