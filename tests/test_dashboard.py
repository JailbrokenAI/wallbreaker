import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from wallbreaker.dashboard.server import create_app  # noqa: E402


def _sessions(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    log = sessions / "run-20260101-000000.jsonl"
    rows = [
        {"kind": "verdict", "label": "COMPLIED", "technique": "godmode_hybrid",
         "payload": "do x", "reason": "full operational detail"},
        {"kind": "verdict", "label": "REFUSED", "technique": "raw",
         "payload": "do y", "reason": "declined"},
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return sessions


def test_health_and_overview(tmp_path):
    client = TestClient(create_app(config=None, sessions_dir=_sessions(tmp_path)))
    assert client.get("/api/health").json()["ok"] is True
    ov = client.get("/api/overview").json()
    assert ov["runs_count"] == 1
    assert ov["findings_count"] == 1
    assert ov["latest_run"] == "run-20260101-000000.jsonl"
    assert ov["config"]["has_target"] is False


def test_findings_runs_arsenal(tmp_path):
    client = TestClient(create_app(config=None, sessions_dir=_sessions(tmp_path)))
    findings = client.get("/api/findings").json()
    assert len(findings) == 1 and findings[0]["label"] == "COMPLIED"
    runs = client.get("/api/runs").json()
    assert runs and runs[0]["name"] == "run-20260101-000000.jsonl"
    assert runs[0]["hits"] == 1
    presets = client.get("/api/presets").json()
    assert any(p["name"] == "variable_z" for p in presets)
    transforms = client.get("/api/transforms").json()
    assert any(t["name"] == "control_char_flood" for t in transforms)


def test_run_detail_path_guard(tmp_path):
    client = TestClient(create_app(config=None, sessions_dir=_sessions(tmp_path)))
    ok = client.get("/api/runs/run-20260101-000000.jsonl")
    assert ok.status_code == 200 and ok.json()["total"] == 2
    bad = client.get("/api/runs/..%2f..%2fetc%2fpasswd")
    assert bad.status_code == 404


def test_fire_requires_target(tmp_path):
    client = TestClient(create_app(config=None, sessions_dir=_sessions(tmp_path)))
    r = client.post("/api/fire", json={"request": "hello"})
    assert r.status_code == 400


def test_compose_builds_payload_without_target(tmp_path):
    client = TestClient(create_app(config=None, sessions_dir=_sessions(tmp_path)))
    r = client.post("/api/compose", json={"request": "hello", "transforms": ["base64"]})
    assert r.status_code == 200
    body = r.json()
    assert body["prompt"] == "hello"
    assert body["payload"] == "aGVsbG8="
    assert body["transforms"] == ["base64"]


def test_fire_records_full_console_attempt(monkeypatch, tmp_path):
    from wallbreaker.config import Config, Endpoint
    from wallbreaker.tools.registry import ToolResult
    import wallbreaker.tools as tools_mod

    sessions = tmp_path / "sessions"
    cfg = Config(
        default_profile="attacker",
        profiles={
            "attacker": Endpoint("attacker", "openai", "http://attacker", "attack-model"),
        },
        target=Endpoint("target", "openai", "http://target", "target-model"),
    )
    seen = {}

    class FakeRegistry:
        async def execute(self, name, args):
            seen["name"] = name
            seen["args"] = args
            return ToolResult("[target fake]\nREFUSED: nope")

    monkeypatch.setattr(tools_mod, "build_registry", lambda _config: FakeRegistry())
    client = TestClient(create_app(config=cfg, sessions_dir=sessions))
    r = client.post("/api/fire", json={"request": "hello", "transforms": ["base64"]})

    assert r.status_code == 200
    body = r.json()
    assert body["payload"] == "aGVsbG8="
    assert body["response"] == "[target fake]\nREFUSED: nope"
    assert body["run_log"].startswith("run-")
    assert seen["name"] == "query_target"
    assert seen["args"]["prompt"] == "hello"
    assert seen["args"]["transforms"] == ["base64"]

    records = [
        json.loads(line)
        for line in (sessions / body["run_log"]).read_text(encoding="utf-8").splitlines()
    ]
    fired = [record for record in records if record.get("kind") == "attack_fire"]
    assert fired
    assert fired[0]["prompt"] == "hello"
    assert fired[0]["payload"] == "aGVsbG8="
    assert fired[0]["response"] == "[target fake]\nREFUSED: nope"
    assert fired[0]["target_model"] == "target-model"


def test_agent_run_requires_target(tmp_path):
    client = TestClient(create_app(config=None, sessions_dir=_sessions(tmp_path)))
    r = client.post("/api/agent/run", json={"objective": "jailbreak the model"})
    assert r.status_code == 400
    assert "target" in r.json()["detail"].lower()


def test_agent_run_requires_objective(tmp_path):
    from wallbreaker.config import Config, Endpoint
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    client = TestClient(create_app(config=cfg, sessions_dir=_sessions(tmp_path)))
    r = client.post("/api/agent/run", json={"objective": "   "})
    assert r.status_code == 400
    assert "objective" in r.json()["detail"].lower()


def test_settings_get_and_set(tmp_path):
    from wallbreaker.config import Config, Endpoint
    cfg = Config(
        default_profile="glm",
        profiles={"glm": Endpoint("glm", "openai", "http://x", "glm-5.2")},
        target=Endpoint("target", "openai", "http://x", "some/text-model"),
        path=tmp_path / "config.toml",
    )
    client = TestClient(create_app(config=cfg, sessions_dir=_sessions(tmp_path)))
    g = client.get("/api/settings").json()
    assert "glm" in g["profiles"]
    assert g["target"]["model"] == "some/text-model"

    r = client.post("/api/settings", json={"target_model": "google/gemini-3-pro-image", "target_modality": "auto"})
    assert r.status_code == 200
    assert r.json()["target"]["model"] == "google/gemini-3-pro-image"
    assert r.json()["target"]["modality"] == "image"

    r2 = client.post("/api/settings", json={"judge_model": "openai/gpt-4o-mini"})
    assert r2.json()["judge_model"] == "openai/gpt-4o-mini"
    assert cfg.target.modality == "image"
