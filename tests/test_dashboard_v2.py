import asyncio
import json
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from wallbreaker.config import Config, Endpoint  # noqa: E402
from wallbreaker.dashboard import server as dashboard_server  # noqa: E402
from wallbreaker.dashboard.server import create_app as _create_app, serve  # noqa: E402


def create_app(*args, **kwargs):
    kwargs.setdefault("require_auth", False)
    return _create_app(*args, **kwargs)


def test_v2_capabilities_include_every_tui_command(tmp_path):
    from wallbreaker.capabilities import TUI_SOURCE

    client = TestClient(create_app(config=None, sessions_dir=tmp_path))
    payload = client.get("/api/v2/capabilities").json()
    represented = {
        token
        for item in payload["capabilities"]
        for token in (item["command"], *item["aliases"])
    }
    assert represented == set(TUI_SOURCE.known_commands)


def test_provider_test_requires_authenticated_inference(tmp_path, monkeypatch):
    endpoint = Endpoint(
        name="strict-test", protocol="openai", base_url="https://example.test/v1",
        model="test-model", api_key="super-secret-invalid-key",
    )
    config = Config(default_profile="strict-test", profiles={"strict-test": endpoint})

    async def fake_discover(name, discovered_endpoint):
        return {
            "profile": name, "protocol": discovered_endpoint.protocol,
            "models": ["test-model"], "fetched": True, "error": "",
        }

    class RejectingProvider:
        async def complete(self, messages, **kwargs):
            raise RuntimeError("401 invalid key super-secret-invalid-key")

        async def aclose(self):
            return None

    monkeypatch.setattr(dashboard_server, "_discover_profile_models", fake_discover)
    monkeypatch.setattr(dashboard_server, "build_provider", lambda endpoint, timeout=None: RejectingProvider())
    response = TestClient(create_app(config=config, sessions_dir=tmp_path)).post(
        "/api/providers/strict-test/test"
    )
    assert response.status_code == 502
    assert "Authenticated inference failed" in response.json()["detail"]
    assert "super-secret-invalid-key" not in response.text


def test_provider_test_reports_verified_model_and_latency(tmp_path, monkeypatch):
    endpoint = Endpoint(
        name="strict-test", protocol="openai", base_url="https://example.test/v1",
        model="test-model", api_key="valid-key",
    )
    config = Config(default_profile="strict-test", profiles={"strict-test": endpoint})

    async def fake_discover(name, discovered_endpoint):
        return {
            "profile": name, "protocol": discovered_endpoint.protocol,
            "models": ["test-model"], "fetched": True, "error": "",
        }

    class AcceptingProvider:
        async def complete(self, messages, **kwargs):
            return "OK"

        async def aclose(self):
            return None

    monkeypatch.setattr(dashboard_server, "_discover_profile_models", fake_discover)
    monkeypatch.setattr(dashboard_server, "build_provider", lambda endpoint, timeout=None: AcceptingProvider())
    response = TestClient(create_app(config=config, sessions_dir=tmp_path)).post(
        "/api/providers/strict-test/test"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["model"] == "test-model"
    assert payload["inference"]["ok"] is True
    assert payload["inference"]["response_preview"] == "OK"


def test_v2_execution_crud_and_validation(tmp_path):
    app = create_app(config=None, sessions_dir=tmp_path)
    client = TestClient(app)
    assert client.post("/api/v2/executions", json={}).status_code == 400
    assert client.post(
        "/api/v2/executions", json={"capability_id": "does.not.exist"}
    ).status_code == 400
    assert client.get("/api/v2/executions").json() == []
    assert client.post("/api/v2/executions/missing/attacker", json={}).status_code == 404


def test_v2_history_search_and_rebuild(tmp_path):
    run = tmp_path / "run-20260801-120000.jsonl"
    run.write_text(
        json.dumps({
            "seq": 1, "ts": "2026-08-01T12:00:00", "kind": "verdict",
            "actor": "judge", "label": "COMPLIED", "technique": "test",
            "reason": "distinctive evidence", "api_key": "must-not-leak",
        }) + "\n",
        encoding="utf-8",
    )
    with TestClient(create_app(config=None, sessions_dir=tmp_path)) as client:
        rebuilt = client.post("/api/v2/history/rebuild").json()
        assert rebuilt["run_count"] == 1
        payload = client.get("/api/v2/history/events", params={"q": "distinctive"}).json()
        assert payload["total"] == 1
        assert "must-not-leak" not in payload["items"][0]["structured_json"]


def test_v2_report_uses_canonical_run_log(tmp_path):
    run = tmp_path / "run-20260801-120000.jsonl"
    run.write_text(
        "\n".join([
            json.dumps({"seq": 1, "ts": "2026-08-01T12:00:00", "kind": "objective", "text": "Evaluate target"}),
            json.dumps({"seq": 2, "ts": "2026-08-01T12:00:01", "kind": "verdict", "label": "COMPLIED", "category": "test", "technique": "pair", "response": "evidence"}),
        ]) + "\n",
        encoding="utf-8",
    )
    with TestClient(create_app(config=None, sessions_dir=tmp_path)) as client:
        response = client.get("/api/v2/reports/run-20260801-120000")
        assert response.status_code == 200
        payload = response.json()
        assert payload["scorecard"]["strict_hits"] == 1
        assert payload["scorecard"]["graded_fires"] == 1
        assert "Evaluate target" in payload["markdown"]
        assert payload["findings"][0]["technique"] == "pair"
        assert client.get("/api/v2/reports/run-20260801-120000.jsonl").status_code == 200


def test_v2_runs_headless_tui_catalog_capability(tmp_path):
    with TestClient(create_app(config=None, sessions_dir=tmp_path)) as client:
        created = client.post(
            "/api/v2/executions",
            json={
                "capability_id": "tui.help",
                "args": {"arguments": "session"},
                "mode": "background",
            },
        )
        assert created.status_code == 200
        execution_id = created.json()["id"]
        for _ in range(50):
            execution = client.get(f"/api/v2/executions/{execution_id}").json()
            if execution["status"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        assert execution["status"] == "succeeded"
        assert "/session" in execution["result"]["content"]


def test_v2_runs_ordered_workflow_and_emits_step_events(tmp_path):
    with TestClient(create_app(config=None, sessions_dir=tmp_path)) as client:
        created = client.post(
            "/api/v2/executions",
            json={
                "capability_id": "workflow.run",
                "args": {
                    "alias": "Session help sequence",
                    "steps": [
                        {"capability_id": "tui.help", "args": {"arguments": "session"}},
                        {"capability_id": "tui.help", "args": {"arguments": "report"}},
                    ],
                },
                "mode": "background",
            },
        )
        assert created.status_code == 200
        execution_id = created.json()["id"]
        for _ in range(50):
            execution = client.get(f"/api/v2/executions/{execution_id}").json()
            if execution["status"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        assert execution["status"] == "succeeded"
        assert [item["capability_id"] for item in execution["result"]["steps"]] == [
            "tui.help", "tui.help",
        ]
        events = client.get(
            f"/api/v2/executions/{execution_id}/events",
            params={"stream": "false"},
        ).json()["events"]
        kinds = [event["type"] for event in events]
        assert kinds.count("workflow_step_started") == 2
        assert kinds.count("workflow_step_succeeded") == 2


def test_v2_rejects_empty_and_recursive_workflows(tmp_path):
    with TestClient(create_app(config=None, sessions_dir=tmp_path)) as client:
        empty = client.post(
            "/api/v2/executions",
            json={"capability_id": "workflow.run", "args": {"steps": []}},
        )
        assert empty.status_code == 200
        execution_id = empty.json()["id"]
        for _ in range(50):
            execution = client.get(f"/api/v2/executions/{execution_id}").json()
            if execution["status"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        assert execution["status"] == "failed"

        recursive = client.post(
            "/api/v2/executions",
            json={
                "capability_id": "workflow.run",
                "args": {"steps": [{"capability_id": "workflow.run", "args": {}}]},
            },
        )
        assert recursive.status_code == 200


def test_parallel_v2_and_legacy_shell_routes(tmp_path):
    web = tmp_path / "web"
    dist = web / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<main>wallbreaker shell</main>", encoding="utf-8")
    with TestClient(create_app(config=None, sessions_dir=tmp_path / "sessions", web_dir=web)) as client:
        assert "wallbreaker shell" in client.get("/v2").text
        assert "wallbreaker shell" in client.get("/legacy").text
        assert "wallbreaker shell" in client.get("/").text


def test_dashboard_reserves_unique_run_paths_within_one_second(tmp_path, monkeypatch):
    from wallbreaker import session as session_mod
    from wallbreaker.dashboard.server import _reserve_runlog_path, _run_time_from_name

    monkeypatch.setattr(session_mod, "_timestamp", lambda: "20260801-120000")
    reserved = set()
    logs = [
        _reserve_runlog_path(session_mod.RunLog(tmp_path), reserved)
        for _ in range(3)
    ]

    assert [log.path.name for log in logs] == [
        "run-20260801-120000.jsonl",
        "run-20260801-120000-01.jsonl",
        "run-20260801-120000-02.jsonl",
    ]
    assert len({log.path for log in logs}) == 3
    assert _run_time_from_name(logs[1].path.name) == "2026-08-01 12:00:00"


def test_dashboard_refuses_network_bind_without_explicit_acknowledgement():
    with pytest.raises(SystemExit):
        serve(host="0.0.0.0")


@pytest.mark.asyncio
async def test_v2_event_cursor_payload_uses_stable_envelope(tmp_path):
    app = create_app(config=None, sessions_dir=tmp_path)
    manager = app.state.execution_manager

    async def runner(ctx):
        ctx.emit("progress", actor="system", text="ready")
        return {"ok": True}

    execution = manager.create("test", {}, runner)
    await execution.task
    events, terminal = await manager.events_after(execution.id, after=2)
    assert terminal is True
    assert events[0].as_dict().keys() == {
        "execution_id", "sequence", "type", "timestamp", "data", "version",
    }
    assert all(event.execution_id == execution.id for event in events)
