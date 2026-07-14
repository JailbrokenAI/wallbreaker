import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from wallbreaker.agent.messages import StopEvent, ToolUseEvent
from wallbreaker.config import Config, Endpoint
from wallbreaker.dashboard.server import create_app
from wallbreaker.provider_registry import ProviderRegistry
from wallbreaker.provider_research import ProviderSpecAgent, fetch_document, normalize_spec_text


class ScriptedProvider:
    def __init__(self, endpoint, events):
        self.endpoint = endpoint
        self.events = list(events)

    async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
        for event in self.events.pop(0):
            yield event


class Search:
    def __init__(self):
        self.queries = []

    async def search(self, query, max_results=5):
        self.queries.append(query)
        return [{"title": "Official docs", "url": "https://vendor.example/docs", "snippet": "API"}]


def _config(tmp_path):
    endpoint = Endpoint("brain", "openai", "https://brain.example/v1", "brain-model")
    return Config(default_profile="brain", profiles={"brain": endpoint}, path=tmp_path / "config.toml")


@pytest.mark.asyncio
async def test_search_only_agent_uses_constrained_search_and_submits(tmp_path):
    cfg = _config(tmp_path)
    search = Search()
    spec = {
        "provider_name": "vendor", "protocol": "openai", "base_url": "https://api.vendor.example/v1",
        "model": "vendor-model", "api_key_env": "VENDOR_API_KEY", "auth_style": "bearer",
        "inference_path": "/chat/completions", "models_path": "/models", "sources": ["https://vendor.example/docs"],
        "confidence": "high", "warnings": [], "supported": True,
    }
    provider = ScriptedProvider(cfg.profile(), [
        [ToolUseEvent("s", "web_search", {"query": "vendor official API docs"}), StopEvent("tool_use")],
        [ToolUseEvent("d", "submit_provider_spec", spec), StopEvent("tool_use")],
    ])
    result = await ProviderSpecAgent(provider, cfg, search).run("vendor")
    assert search.queries == ["vendor official API docs"]
    assert result["models_path"] == "/models"
    assert result["supported"] is True


def test_yaml_spec_is_parsed_as_structured_content():
    normalized = normalize_spec_text("openapi: 3.1.0\ninfo:\n  title: Example")
    assert json.loads(normalized)["openapi"] == "3.1.0"


@pytest.mark.asyncio
async def test_document_fetch_rejects_non_http_urls():
    with pytest.raises(ValueError, match="HTTP"):
        await fetch_document("file:///tmp/provider.yaml")


def test_draft_requires_explicit_apply(tmp_path):
    cfg = _config(tmp_path)
    registry = ProviderRegistry(cfg)
    draft = registry.save_draft({
        "provider_name": "new-provider", "protocol": "openai",
        "base_url": "https://new.example/v1", "model": "new-model",
        "sources": ["https://new.example/docs"], "supported": True,
    })
    assert "new-provider" not in cfg.profiles
    applied = registry.apply_draft(draft["id"])
    assert applied["name"] == "new-provider"
    assert cfg.profiles["new-provider"].model == "new-model"


def test_unsupported_draft_cannot_be_applied(tmp_path):
    cfg = _config(tmp_path)
    registry = ProviderRegistry(cfg)
    draft = registry.save_draft({
        "provider_name": "custom", "protocol": "unsupported", "base_url": "https://custom.example",
        "model": "x", "sources": [], "supported": False,
    })
    with pytest.raises(Exception, match="custom provider adapter"):
        registry.apply_draft(draft["id"])


def test_draft_api_edits_and_discards_without_activation(tmp_path):
    cfg = _config(tmp_path)
    registry = ProviderRegistry(cfg)
    draft = registry.save_draft({
        "provider_name": "pending", "protocol": "openai", "base_url": "https://pending.example/v1",
        "model": "old", "sources": [], "supported": True,
    })
    client = TestClient(create_app(config=cfg, sessions_dir=tmp_path / "sessions"))
    updated = client.put(f"/api/provider-spec/drafts/{draft['id']}", json={"model": "edited"})
    assert updated.status_code == 200
    assert updated.json()["model"] == "edited"
    assert "pending" not in cfg.profiles
    assert client.delete(f"/api/provider-spec/drafts/{draft['id']}").json() == {"ok": True}


def test_discovery_sse_persists_reviewable_draft(monkeypatch, tmp_path):
    cfg = _config(tmp_path)

    async def fake_run(self, provider_name, docs_urls=None, spec_text="", notes="", max_rounds=6,
                       max_tokens=8192, emit=lambda _event: None):
        emit({"type": "fetch", "url": docs_urls[0]})
        return {
            "provider_name": provider_name, "protocol": "openai",
            "base_url": "https://api.vendor.example/v1", "model": "vendor-model",
            "api_key_env": "VENDOR_API_KEY", "auth_style": "bearer",
            "inference_path": "/chat/completions", "models_path": "/models",
            "modality": "text", "response_shape": "choices[].message",
            "sources": docs_urls, "confidence": "high", "warnings": [], "supported": True,
        }

    monkeypatch.setattr(ProviderSpecAgent, "run", fake_run)
    client = TestClient(create_app(config=cfg, sessions_dir=tmp_path / "sessions"))
    response = client.post("/api/provider-spec/discover", json={
        "provider_name": "vendor", "docs_urls": ["https://vendor.example/docs"],
    })
    assert response.status_code == 200
    assert '"type": "done"' in response.text
    drafts = client.get("/api/provider-spec/drafts").json()
    assert drafts[0]["provider_name"] == "vendor"
    assert "vendor" not in cfg.profiles
