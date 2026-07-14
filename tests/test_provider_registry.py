import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from wallbreaker.config import Config, Endpoint
from wallbreaker.dashboard.server import create_app


def _config(tmp_path):
    return Config(
        default_profile="base",
        profiles={"base": Endpoint("base", "openai", "https://base.example/v1", "base-model")},
        target=Endpoint("target", "openai", "https://base.example/v1", "target-model"),
        path=tmp_path / "config.toml",
    )


def test_provider_crud_redacts_key_and_updates_env(tmp_path):
    cfg = _config(tmp_path)
    client = TestClient(create_app(config=cfg, sessions_dir=tmp_path / "sessions"))
    response = client.put("/api/providers/custom", json={
        "protocol": "openai",
        "base_url": "https://custom.example/v1/",
        "model": "custom-model",
        "api_key_env": "CUSTOM_API_KEY",
        "api_key": "top-secret",
        "models_path": "/catalog/models",
    })
    assert response.status_code == 200
    assert response.json()["has_api_key"] is True
    assert "api_key" not in response.json()
    assert "top-secret" not in client.get("/api/providers").text
    assert "CUSTOM_API_KEY='top-secret'" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert cfg.profiles["custom"].models_path == "/catalog/models"
    persisted = json.loads((tmp_path / ".wallbreaker_providers.json").read_text())
    assert persisted["providers"]["custom"]["model"] == "custom-model"

    assert client.delete("/api/providers/custom").json() == {"ok": True}
    assert "custom" not in cfg.profiles


def test_config_provider_can_be_overridden_then_reset(tmp_path):
    cfg = _config(tmp_path)
    client = TestClient(create_app(config=cfg, sessions_dir=tmp_path / "sessions"))
    changed = client.put("/api/providers/base", json={"model": "override-model"})
    assert changed.json()["model"] == "override-model"
    assert changed.json()["can_reset"] is True
    reset = client.post("/api/providers/base/reset")
    assert reset.status_code == 200
    assert reset.json()["model"] == "base-model"


def test_roles_are_independent_and_persisted(tmp_path):
    cfg = _config(tmp_path)
    cfg.profiles["other"] = Endpoint("other", "anthropic", "https://other.example", "other-default")
    client = TestClient(create_app(config=cfg, sessions_dir=tmp_path / "sessions"))
    assert client.put("/api/roles/attacker", json={"provider": "other", "model": "attack-x"}).status_code == 200
    assert client.put("/api/roles/target", json={"provider": "base", "model": "target-x"}).status_code == 200
    research = client.put("/api/roles/research", json={
        "provider": "other", "model": "research-x", "max_rounds": 9, "max_tokens": 12000,
    })
    assert research.json()["max_rounds"] == 9
    roles = client.get("/api/roles").json()
    assert roles["attacker"] == {"provider": "other", "model": "attack-x"}
    assert roles["target"] == {"provider": "base", "model": "target-x"}
    assert roles["research"]["model"] == "research-x"
    state = json.loads((tmp_path / ".wallbreaker_state.json").read_text())
    assert state["research_profile"] == "other"


def test_provider_validation_and_localhost_cors(tmp_path):
    client = TestClient(create_app(config=_config(tmp_path), sessions_dir=tmp_path / "sessions"))
    bad = client.put("/api/providers/nope", json={"protocol": "unknown", "model": "x"})
    assert bad.status_code == 400
    allowed = client.options("/api/providers", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET",
    })
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
