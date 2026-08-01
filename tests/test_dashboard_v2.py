import asyncio
import json
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from wallbreaker.dashboard.server import create_app, serve  # noqa: E402


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


def test_parallel_v2_and_legacy_shell_routes(tmp_path):
    web = tmp_path / "web"
    dist = web / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<main>wallbreaker shell</main>", encoding="utf-8")
    with TestClient(create_app(config=None, sessions_dir=tmp_path / "sessions", web_dir=web)) as client:
        assert "wallbreaker shell" in client.get("/v2").text
        assert "wallbreaker shell" in client.get("/legacy").text
        assert "wallbreaker shell" in client.get("/").text


def test_dashboard_refuses_network_bind_without_explicit_acknowledgement():
    with pytest.raises(ValueError, match="unauthenticated dashboard"):
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
