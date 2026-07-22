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
        {"kind": "run_meta", "models": {
            "attacker": "attacker-per-run", "target": "target-per-run", "judge": "judge-per-run",
        }},
        {"kind": "verdict", "label": "COMPLIED", "technique": "godmode_hybrid",
         "payload": "do x", "reason": "full operational detail"},
        {"kind": "verdict", "label": "REFUSED", "technique": "raw",
         "payload": "do y", "reason": "declined"},
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return sessions


def test_health_and_overview(tmp_path):
    client = TestClient(create_app(config=None, sessions_dir=_sessions(tmp_path), require_auth=False))
    assert client.get("/api/health").json()["ok"] is True
    ov = client.get("/api/overview").json()
    assert ov["runs_count"] == 1
    assert ov["findings_count"] == 1
    assert ov["latest_run"] == "run-20260101-000000.jsonl"
    assert ov["config"]["has_target"] is False


def test_findings_runs_arsenal(tmp_path):
    client = TestClient(create_app(config=None, sessions_dir=_sessions(tmp_path), require_auth=False))
    findings = client.get("/api/findings").json()
    assert len(findings) == 1 and findings[0]["label"] == "COMPLIED"
    assert findings[0]["run"] == "run-20260101-000000.jsonl"
    assert findings[0]["run_time"] == "2026-01-01 00:00:00"
    assert findings[0]["models"]["target"] == "target-per-run"
    assert findings[0]["conversation"]
    runs = client.get("/api/runs").json()
    assert runs and runs[0]["name"] == "run-20260101-000000.jsonl"
    assert runs[0]["hits"] == 1
    assert runs[0]["models"]["target"] == "target-per-run"
    presets = client.get("/api/presets").json()
    assert any(p["name"] == "variable_z" for p in presets)
    assert all(p["template"] for p in presets)
    assert all("{request}" in p["template"] for p in presets)
    transforms = client.get("/api/transforms").json()
    assert any(t["name"] == "control_char_flood" for t in transforms)


def test_findings_can_select_multiple_past_runs(tmp_path):
    sessions = _sessions(tmp_path)
    older = sessions / "run-20251231-235959.jsonl"
    older.write_text(
        "\n".join([
            json.dumps({"kind": "objective", "text": "older objective"}),
            json.dumps({
                "kind": "tool_call",
                "tool": "query_target",
                "args": {"prompt": "older payload", "transforms": ["base64"]},
            }),
            json.dumps({
                "kind": "tool_result",
                "tool": "query_target",
                "content": "older response",
                "error": False,
            }),
            json.dumps({
                "kind": "verdict",
                "label": "PARTIAL",
                "payload": "older payload",
                "response": "older response",
                "reason": "partial detail",
                "technique": "query_target",
                "target_model": "older-target-model",
            }),
        ]),
        encoding="utf-8",
    )

    client = TestClient(create_app(config=None, sessions_dir=sessions, require_auth=False))
    runs = client.get("/api/findings/runs").json()
    assert [r["name"] for r in runs][:2] == [
        "run-20260101-000000.jsonl",
        "run-20251231-235959.jsonl",
    ]

    findings = client.get(
        "/api/findings",
        params={"runs": "run-20260101-000000.jsonl,run-20251231-235959.jsonl"},
    ).json()
    assert {f["run"] for f in findings} == {
        "run-20260101-000000.jsonl",
        "run-20251231-235959.jsonl",
    }
    older_finding = next(f for f in findings if f["run"] == "run-20251231-235959.jsonl")
    assert older_finding["run_time"] == "2025-12-31 23:59:59"
    assert older_finding["models"]["target"] == "older-target-model"
    assert older_finding["technique_detail"]["transforms"]["prompt"] == ["base64"]
    assert [turn["role"] for turn in older_finding["conversation"]] == ["user", "assistant"]
    assert older_finding["judging"]["criteria"]


def test_run_detail_path_guard(tmp_path):
    client = TestClient(create_app(config=None, sessions_dir=_sessions(tmp_path), require_auth=False))
    ok = client.get("/api/runs/run-20260101-000000.jsonl")
    assert ok.status_code == 200 and ok.json()["total"] == 3
    bad = client.get("/api/runs/..%2f..%2fetc%2fpasswd")
    assert bad.status_code == 404


def test_fire_requires_target(tmp_path):
    client = TestClient(create_app(config=None, sessions_dir=_sessions(tmp_path), require_auth=False))
    r = client.post("/api/fire", json={"request": "hello"})
    assert r.status_code == 400


def test_compose_builds_payload_without_target(tmp_path):
    client = TestClient(create_app(config=None, sessions_dir=_sessions(tmp_path), require_auth=False))
    r = client.post("/api/compose", json={"request": "hello", "transforms": ["base64"]})
    assert r.status_code == 200
    body = r.json()
    assert body["prompt"] == "hello"
    assert body["payload"] == "aGVsbG8="
    assert body["transforms"] == ["base64"]


def test_fire_records_full_console_attempt(monkeypatch, tmp_path):
    from wallbreaker.agent.messages import ReasoningDelta, StopEvent, TextDelta, UsageEvent, user
    from wallbreaker.config import Config, Endpoint
    from wallbreaker.providers.base import Provider
    from wallbreaker.tools.registry import ToolResult
    import wallbreaker.tools as tools_mod

    sessions = tmp_path / "sessions"
    cfg = Config(
        default_profile="attacker",
        profiles={
            "attacker": Endpoint("attacker", "openai", "http://attacker", "attack-model"),
        },
        target=Endpoint("target", "openai", "http://target", "target-model"),
        path=tmp_path / "config.toml",
    )
    seen = {}

    class FakeProvider(Provider):
        async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
            yield ReasoningDelta("full target reasoning")
            yield TextDelta("[target fake]\nREFUSED: nope")
            yield UsageEvent(17, 9)
            yield StopEvent("end_turn")

    class FakeRegistry:
        async def execute(self, name, args):
            seen["name"] = name
            seen["args"] = args
            content = await FakeProvider(cfg.target).complete(
                [user(args["prompt"])], system=args.get("system"),
                max_tokens=args.get("max_tokens", 1024),
            )
            return ToolResult(content)

    monkeypatch.setattr(tools_mod, "build_registry", lambda _config: FakeRegistry())
    client = TestClient(create_app(config=cfg, sessions_dir=sessions, require_auth=False))
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
    response = next(record for record in records if record.get("kind") == "target")
    request = response["request"]
    assert response["action"] == "complete"
    assert request["messages"][0]["content"][0]["text"] == "hello"
    assert request["parameters"]["max_tokens"] == 1024
    assert response["text"] == "[target fake]\nREFUSED: nope"
    assert response["reasoning"] == "full target reasoning"
    assert response["usage_events"] == [{"input_tokens": 17, "output_tokens": 9}]
    assert response["stop_reasons"] == ["end_turn"]
    assert [part["channel"] for part in response["stream"]] == ["reasoning", "text"]
    assert [event["type"] for event in response["stream_metadata"]] == ["usage", "stop"]


def test_agent_run_logs_full_scaffold_inference_and_tools(monkeypatch, tmp_path):
    from wallbreaker.agent.messages import (
        ReasoningDelta, StopEvent, TextDelta, ToolUseEvent, UsageEvent,
    )
    from wallbreaker.config import Config, Endpoint
    from wallbreaker.providers.base import Provider
    from wallbreaker.tools.registry import ToolContext, ToolRegistry
    import wallbreaker.providers.factory as factory_mod
    import wallbreaker.tools as tools_mod

    sessions = tmp_path / "sessions"
    sessions.mkdir()
    attacker = Endpoint("attacker", "openai", "http://attacker", "attack-model")
    target = Endpoint("target", "openai", "http://target", "target-model")
    cfg = Config(
        default_profile="attacker", profiles={"attacker": attacker},
        target=target, path=tmp_path / "config.toml",
    )

    class FakeProvider(Provider):
        async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
            yield ReasoningDelta("private attacker reasoning")
            yield TextDelta("attacker visible output")
            yield ToolUseEvent("finish-1", "finish", {"summary": "complete summary text"})
            yield UsageEvent(101, 37)
            yield StopEvent("tool_use")

    registry = ToolRegistry(ToolContext(config=cfg))

    async def finish(args, _ctx):
        return f"finish accepted: {args['summary']}"

    registry.add(
        "finish", "Finish the autonomous engagement with a complete summary.",
        {
            "type": "object",
            "properties": {"summary": {"type": "string", "description": "Full summary text"}},
            "required": ["summary"],
        },
        finish,
    )
    monkeypatch.setattr(factory_mod, "build_provider", lambda _endpoint: FakeProvider(attacker))
    monkeypatch.setattr(tools_mod, "build_registry", lambda _config: registry)

    client = TestClient(create_app(config=cfg, sessions_dir=sessions, require_auth=False))
    with client.stream("POST", "/api/agent/run", json={
        "objective": "full objective text", "max_rounds": 1, "max_tokens": 2048,
    }) as response:
        assert response.status_code == 200
        stream_text = "".join(response.iter_text())
    assert '"type": "done"' in stream_text

    log = next(sessions.glob("run-*.jsonl"))
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert next(row for row in records if row["kind"] == "run_meta")["source"] == "dashboard_agent"
    response_record = next(row for row in records if row["kind"] == "scaffold")
    request = response_record["request"]
    tool_call = next(row for row in records if row["kind"] == "tool_call")
    tool_result = next(row for row in records if row["kind"] == "tool_result")

    assert response_record["action"] == "plan_and_route"
    assert request["system"]
    assert request["messages"][0]["content"][0]["text"] == "full objective text"
    assert request["tools"][0]["description"].startswith("Finish the autonomous")
    assert request["parameters"]["max_tokens"] == 2048
    assert response_record["text"] == "attacker visible output"
    assert response_record["reasoning"] == "private attacker reasoning"
    assert response_record["usage_events"] == [{"input_tokens": 101, "output_tokens": 37}]
    assert response_record["stop_reasons"] == ["tool_use"]
    assert [part["channel"] for part in response_record["stream"]] == ["reasoning", "text"]
    assert [event["type"] for event in response_record["stream_metadata"]] == [
        "tool_use", "usage", "stop",
    ]
    assert tool_call["args"] == {"summary": "complete summary text"}
    assert tool_result["content"] == "finish accepted: complete summary text"
    assert any(row["kind"] == "agent_done" and row["status"] == "finished" for row in records)


def test_agent_run_requires_target(tmp_path):
    client = TestClient(create_app(config=None, sessions_dir=_sessions(tmp_path), require_auth=False))
    r = client.post("/api/agent/run", json={"objective": "jailbreak the model"})
    assert r.status_code == 400
    assert "target" in r.json()["detail"].lower()


def test_agent_run_requires_objective(tmp_path):
    from wallbreaker.config import Config, Endpoint
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    client = TestClient(create_app(config=cfg, sessions_dir=_sessions(tmp_path), require_auth=False))
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
    client = TestClient(create_app(config=cfg, sessions_dir=_sessions(tmp_path), require_auth=False))
    g = client.get("/api/settings").json()
    assert "glm" in g["profiles"]
    assert g["profile_details"]["glm"]["model"] == "glm-5.2"
    assert g["target"]["model"] == "some/text-model"
    assert g["agent"]["max_rounds"] == 8
    assert g["agent"]["max_tokens"] == 8192
    assert g["agent"]["concurrency"] == 3
    assert g["agent"]["request_delay_ms"] == 250
    assert g["target_options"] == {
        "modality": "auto", "system_mode": "default", "provider": "",
        "judge_enabled": True,
    }

    r = client.post("/api/settings", json={"target_model": "google/gemini-3-pro-image", "target_modality": "auto"})
    assert r.status_code == 200
    assert r.json()["target"]["model"] == "google/gemini-3-pro-image"
    assert r.json()["target"]["modality"] == "image"

    r2 = client.post("/api/settings", json={"judge_model": "openai/gpt-4o-mini"})
    assert r2.json()["judge_model"] == "openai/gpt-4o-mini"
    # Role choices resolve per run and never mutate the provider/global config.
    assert cfg.target.modality == "text"

    r3 = client.post("/api/settings", json={"agent": {
        "max_rounds": 18, "max_tokens": 12000,
        "concurrency": 5, "request_delay_ms": 75,
    }})
    assert r3.json()["agent"] == {
        "max_rounds": 18, "max_tokens": 12000,
        "concurrency": 5, "request_delay_ms": 75,
    }

    low_tokens = client.post("/api/settings", json={"agent": {"max_tokens": 7}})
    assert low_tokens.json()["agent"]["max_tokens"] == 7

    r4 = client.post("/api/settings", json={"target_options": {
        "modality": "image", "system_mode": "merge", "provider": "WandB, Alibaba",
        "judge_enabled": False,
    }})
    assert r4.json()["target_options"] == {
        "modality": "image", "system_mode": "merge", "provider": "WandB, Alibaba",
        "judge_enabled": False,
    }

    from wallbreaker.agent_profiles import resolved_config
    from wallbreaker.dashboard.server import _apply_target_settings
    from wallbreaker.state import load_state, state_path_for

    run_config, _ = resolved_config(cfg)
    applied = _apply_target_settings(run_config, load_state(state_path_for(cfg)))
    assert applied.target.modality == "image"
    assert applied.target.system_mode == "merge"
    assert applied.target.provider == ("WandB", "Alibaba")
    assert applied.judge_enabled is False

    from wallbreaker.tools import build_registry
    assert build_registry(applied).ctx.judge_endpoint is None
    # Dashboard target controls are run-scoped and do not mutate provider records.
    assert cfg.target.system_mode == "default"
    assert cfg.target.provider == ()



def test_models_fetches_catalog_for_profile(monkeypatch, tmp_path):
    from wallbreaker.config import Config, Endpoint
    import httpx

    cfg = Config(
        default_profile="router",
        profiles={
            "router": Endpoint(
                "router", "openai", "https://router.example/v1", "current-model",
                api_key="secret",
            ),
        },
        path=tmp_path / "config.toml",
    )
    seen = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "z-model"}, {"id": "a-model"}]}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, headers):
            seen["url"] = url
            seen["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    client = TestClient(create_app(config=cfg, sessions_dir=_sessions(tmp_path), require_auth=False))
    response = client.get("/api/models", params={"profile": "router"})

    assert response.status_code == 200
    assert response.json()["models"] == ["a-model", "current-model", "z-model"]
    assert response.json()["fetched"] is True
    assert seen["url"] == "https://router.example/v1/models"
    assert seen["headers"]["Authorization"] == "Bearer secret"


def test_models_catalog_failure_keeps_current_model(monkeypatch, tmp_path):
    from wallbreaker.config import Config, Endpoint
    import httpx

    cfg = Config(
        default_profile="router",
        profiles={"router": Endpoint("router", "openai", "https://router.example/v1", "current-model")},
        path=tmp_path / "config.toml",
    )

    class FailingClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, headers=None):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "AsyncClient", FailingClient)
    client = TestClient(create_app(config=cfg, sessions_dir=_sessions(tmp_path), require_auth=False))
    response = client.get("/api/models", params={"profile": "router"})

    assert response.status_code == 200
    assert response.json()["models"] == ["current-model"]
    assert response.json()["fetched"] is False
    assert "unavailable" in response.json()["error"].lower()


def test_target_profile_and_custom_model_persist_together(tmp_path):
    from wallbreaker.config import Config, Endpoint
    from wallbreaker.agent_profiles import resolve_role

    cfg = Config(
        default_profile="one",
        profiles={
            "one": Endpoint("one", "openai", "https://one.example/v1", "one-model"),
            "two": Endpoint("two", "openai", "https://two.example/v1", "two-model"),
        },
        target=Endpoint("target", "openai", "https://one.example/v1", "old-model"),
        path=tmp_path / "config.toml",
    )
    client = TestClient(create_app(config=cfg, sessions_dir=_sessions(tmp_path), require_auth=False))
    response = client.post(
        "/api/settings",
        json={"target_profile": "two", "target_model": "custom-model"},
    )

    assert response.status_code == 200
    assert response.json()["target"]["model"] == "custom-model"
    assert response.json()["target"]["base_url"] == "https://two.example/v1"
    resolved_target, _ = resolve_role(cfg, "target")
    assert resolved_target.base_url == "https://two.example/v1"
    assert resolved_target.model == "custom-model"
    assert "[agents.target]" in cfg.path.read_text(encoding="utf-8")

    judge_response = client.post(
        "/api/settings",
        json={"judge_profile": "two", "judge_model": "judge-model"},
    )
    assert judge_response.status_code == 200
    assert judge_response.json()["judge_model"] == "judge-model"
    resolved_judge, _ = resolve_role(cfg, "judge")
    assert resolved_judge.base_url == "https://two.example/v1"
