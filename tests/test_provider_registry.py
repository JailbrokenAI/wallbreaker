import json
import tomllib

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from wallbreaker.config import Config, Endpoint, load_config
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
    client = TestClient(create_app(config=cfg, sessions_dir=tmp_path / "sessions", require_auth=False))
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
    assert response.json()["api_key_env"] == "CUSTOM_API_KEY"
    assert "api_key" not in response.json()
    assert "top-secret" not in client.get("/api/providers").text
    assert "CUSTOM_API_KEY='top-secret'" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert cfg.profiles["custom"].models_path == "/catalog/models"
    persisted = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert persisted["profiles"]["custom"]["model"] == "custom-model"

    updated = client.put("/api/providers/custom", json={
        "api_key_env": "CUSTOM_API_KEY",
        "api_key": "replacement-secret",
    })
    assert updated.status_code == 200
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "CUSTOM_API_KEY='replacement-secret'" in env_text
    assert "top-secret" not in env_text

    assert client.delete("/api/providers/custom").json() == {"ok": True}
    assert "custom" not in cfg.profiles
    assert all(item["name"] != "custom" for item in client.get("/api/providers").json())
    persisted = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert "custom" not in persisted["profiles"]


def test_provider_can_be_saved_and_tested_without_default_model(monkeypatch, tmp_path):
    import wallbreaker.dashboard.server as server_mod

    cfg = _config(tmp_path)

    async def discover(name, endpoint):
        assert name == "catalog-only"
        assert endpoint.model == ""
        return {
            "profile": name,
            "protocol": endpoint.protocol,
            "models": ["vendor/model-a", "vendor/model-b"],
            "fetched": True,
            "cached": False,
            "refreshed_at": "",
            "error": "",
        }

    monkeypatch.setattr(server_mod, "_discover_profile_models", discover)
    client = TestClient(create_app(config=cfg, sessions_dir=tmp_path / "sessions", require_auth=False))
    saved = client.put("/api/providers/catalog-only", json={
        "protocol": "openai",
        "base_url": "https://catalog.example/v1",
        "api_key_env": "CATALOG_API_KEY",
        "model": "",
        "enabled": False,
    })

    assert saved.status_code == 200
    assert saved.json()["model"] == ""
    assert saved.json()["enabled"] is False
    persisted = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert "model" not in persisted["profiles"]["catalog-only"]
    assert load_config(tmp_path / "config.toml").all_profiles["catalog-only"].model == ""

    tested = client.post("/api/providers/catalog-only/test")
    assert tested.status_code == 200
    assert tested.json()["models"] == ["vendor/model-a", "vendor/model-b"]
    catalog = client.get("/api/models", params={"profile": "catalog-only"})
    assert catalog.status_code == 200
    assert catalog.json()["models"] == ["vendor/model-a", "vendor/model-b"]


def test_config_provider_can_be_edited_like_any_other_provider(tmp_path):
    cfg = _config(tmp_path)
    client = TestClient(create_app(config=cfg, sessions_dir=tmp_path / "sessions", require_auth=False))
    changed = client.put("/api/providers/base", json={"model": "override-model"})
    assert changed.json()["model"] == "override-model"
    assert cfg.profiles["base"].model == "override-model"
    persisted = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert persisted["profiles"]["base"]["model"] == "override-model"


def test_config_provider_can_be_disabled_then_enabled(tmp_path):
    cfg = _config(tmp_path)
    client = TestClient(create_app(config=cfg, sessions_dir=tmp_path / "sessions", require_auth=False))

    assert client.put("/api/providers/other", json={
        "protocol": "openai", "base_url": "https://other.example/v1", "model": "other-model",
    }).status_code == 200
    disabled_response = client.put("/api/providers/base", json={"enabled": False})
    assert disabled_response.status_code == 200
    disabled = next(item for item in client.get("/api/providers").json() if item["name"] == "base")
    assert disabled["enabled"] is False
    assert "base" not in cfg.profiles
    persisted = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert persisted["profiles"]["base"]["enabled"] is False
    reloaded = load_config(tmp_path / "config.toml")
    assert "base" not in reloaded.profiles
    assert reloaded.all_profiles["base"].model == "base-model"

    enabled = client.put("/api/providers/base", json={"enabled": True})
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert cfg.profiles["base"].model == "base-model"
    persisted = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert "enabled" not in persisted["profiles"]["base"]


def test_config_provider_can_be_removed_and_recreated(tmp_path):
    cfg = _config(tmp_path)
    client = TestClient(create_app(config=cfg, sessions_dir=tmp_path / "sessions", require_auth=False))

    added = client.put("/api/providers/other", json={
        "protocol": "openai", "base_url": "https://other.example/v1", "model": "other-model",
    })
    assert added.status_code == 200
    assert client.delete("/api/providers/base").json() == {"ok": True}
    assert all(item["name"] != "base" for item in client.get("/api/providers").json())
    assert "base" not in cfg.profiles
    persisted = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert "base" not in persisted["profiles"]

    recreated = client.put("/api/providers/base", json={
        "protocol": "openai", "base_url": "https://base.example/v1",
        "model": "base-model", "enabled": True,
    })
    assert recreated.status_code == 200
    assert recreated.json()["enabled"] is True
    assert cfg.profiles["base"].model == "base-model"


def test_roles_are_independent_and_persisted(tmp_path):
    cfg = _config(tmp_path)
    cfg.profiles["other"] = Endpoint("other", "anthropic", "https://other.example", "other-default")
    client = TestClient(create_app(config=cfg, sessions_dir=tmp_path / "sessions", require_auth=False))
    assert client.put("/api/roles/attacker", json={"provider": "other", "model": "attack-x"}).status_code == 200
    assert client.put("/api/roles/target", json={"provider": "base", "model": "target-x"}).status_code == 200
    roles = client.get("/api/roles").json()
    assert roles["attacker"]["provider"] == "other"
    assert roles["attacker"]["model"] == "attack-x"
    assert roles["attacker"]["custom"] is True
    assert roles["target"]["provider"] == "base"
    assert roles["target"]["model"] == "target-x"
    text = cfg.path.read_text(encoding="utf-8")
    assert "[agents.attacker]" in text
    assert 'provider = "other"' in text
    assert set(roles) == {"attacker", "target", "judge"}
    assert client.put("/api/roles/research", json={
        "provider": "other", "model": "unused",
    }).status_code == 404


def test_dashboard_removes_obsolete_provider_research_state(tmp_path):
    cfg = _config(tmp_path)
    state_path = tmp_path / ".wallbreaker_state.json"
    state_path.write_text(json.dumps({
        "profile": "base",
        "research_profile": "base",
        "research_model": "obsolete-model",
        "research_agent_max_rounds": 9,
        "research_agent_max_tokens": 12000,
    }), encoding="utf-8")

    TestClient(create_app(config=cfg, sessions_dir=tmp_path / "sessions", require_auth=False))
    assert json.loads(state_path.read_text(encoding="utf-8")) == {}


def test_provider_validation_and_localhost_cors(tmp_path):
    client = TestClient(create_app(config=_config(tmp_path), sessions_dir=tmp_path / "sessions", require_auth=False))
    bad = client.put("/api/providers/nope", json={"protocol": "unknown", "model": "x"})
    assert bad.status_code == 400
    allowed = client.options("/api/providers", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET",
    })
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
