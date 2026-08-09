import asyncio

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from wallbreaker.dashboard.server import _LiveAttackerProvider, create_app  # noqa: E402


def test_live_attacker_uses_switched_provider_and_system():
    from wallbreaker.agent.messages import StopEvent, TextDelta
    from wallbreaker.config import Endpoint

    class FakeProvider:
        def __init__(self, endpoint, text):
            self.endpoint = endpoint
            self.text = text
            self.systems = []

        async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
            self.systems.append(system)
            yield TextDelta(self.text)
            yield StopEvent("end_turn")

    async def exercise():
        first_endpoint = Endpoint("attacker", "openai", "http://one", "one")
        second_endpoint = Endpoint("attacker", "openai", "http://two", "two")
        first = FakeProvider(first_endpoint, "first")
        second = FakeProvider(second_endpoint, "second")
        live = _LiveAttackerProvider(first, first_endpoint, lambda endpoint: f"system:{endpoint.model}")

        async def collect():
            return [event async for event in live.stream([])]

        live.switch(second, second_endpoint)
        events = await collect()
        assert events[0].text == "second"
        assert second.systems == ["system:two"]
        assert first.systems == []

    asyncio.run(exercise())


def test_pause_gate_applies_steering_to_first_resumed_turn():
    from wallbreaker.agent.loop import run_turn
    from wallbreaker.agent.messages import StopEvent, TextDelta, user

    seen = []

    class FakeProvider:
        async def stream(self, history, tools=None, system=None, max_tokens=4096, temperature=None):
            seen.append([message.text() for message in history])
            yield TextDelta("done")
            yield StopEvent("end_turn")

    async def exercise():
        resume = asyncio.Event()
        queued = []
        history = [user("objective")]
        task = asyncio.create_task(run_turn(
            FakeProvider(), None, history,
            feedback=lambda: queued[:], before_model=resume.wait,
        ))
        await asyncio.sleep(0)
        assert not task.done()
        queued.append("pivot while paused")
        resume.set()
        await task

    asyncio.run(exercise())
    assert "pivot while paused" in seen[0][-1]


def test_agent_control_routes_report_inactive(tmp_path):
    client = TestClient(create_app(config=None, sessions_dir=tmp_path, require_auth=False))
    assert client.get("/api/agent/status").json() == {
        "active": False,
        "paused": False,
        "pause_ready": False,
        "stopping": False,
        "attacker": "",
        "provider": "",
        "objective": "",
    }
    assert client.post("/api/agent/pause").status_code == 409
    assert client.post("/api/agent/resume").status_code == 409
    assert client.post("/api/agent/stop").status_code == 409
    assert client.post("/api/agent/steer", json={"message": "pivot"}).status_code == 409
    assert client.post("/api/agent/attacker", json={"provider": "x", "model": "y"}).status_code == 409


def test_should_stop_ends_autonomous_run():
    from wallbreaker.agent.loop import run_autonomous
    from wallbreaker.agent.messages import StopEvent, TextDelta, user

    class FakeProvider:
        async def stream(self, history, tools=None, system=None, max_tokens=4096, temperature=None):
            yield TextDelta("still going")
            yield StopEvent("end_turn")

    async def exercise():
        history = [user("objective")]
        stop_at = {"n": 0}

        def should_stop():
            stop_at["n"] += 1
            return stop_at["n"] >= 1

        return await run_autonomous(
            FakeProvider(),
            None,
            history,
            max_rounds=5,
            should_stop=should_stop,
        )

    result = asyncio.run(exercise())
    assert result.status == "stopped"
    assert "ended" in (result.data or {}).get("summary", "")


def test_cancelled_tool_execution_ends_as_stopped():
    from wallbreaker.agent.loop import run_autonomous
    from wallbreaker.agent.messages import StopEvent, ToolUseEvent, user
    from wallbreaker.tools.registry import ToolContext, ToolRegistry, ToolResult

    class FakeProvider:
        async def stream(self, history, tools=None, system=None, max_tokens=4096, temperature=None):
            yield ToolUseEvent("t1", "slow_tool", {})
            yield StopEvent("tool_use")

    async def slow_tool(_args, _ctx):
        await asyncio.sleep(30)
        return "should not finish"

    async def exercise():
        reg = ToolRegistry(ToolContext(config=None))  # type: ignore[arg-type]
        reg.add("slow_tool", "slow", {"type": "object", "properties": {}}, slow_tool)
        history = [user("objective")]
        task = asyncio.create_task(
            run_autonomous(FakeProvider(), reg, history, max_rounds=3)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        return await task

    result = asyncio.run(exercise())
    assert result.status == "stopped"


def test_agent_run_filters_optional_techniques_but_keeps_controls(monkeypatch, tmp_path):
    from wallbreaker.agent.messages import StopEvent, ToolUseEvent
    from wallbreaker.config import Config, Endpoint
    from wallbreaker.tools.registry import ToolContext, ToolRegistry
    import wallbreaker.providers.factory as factory_mod
    import wallbreaker.tools as tools_mod

    attacker = Endpoint("attacker", "openai", "http://attacker", "attack-model")
    target = Endpoint("target", "openai", "http://target", "target-model")
    config = Config(
        default_profile="attacker", profiles={"attacker": attacker}, target=target,
        path=tmp_path / "config.toml",
    )
    seen_tools = []

    class FakeProvider:
        endpoint = attacker

        async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
            seen_tools.extend(spec["name"] for spec in (tools or []))
            yield ToolUseEvent("finish-1", "finish", {"summary": "done"})
            yield StopEvent("tool_use")

    registry = ToolRegistry(ToolContext(config=config))

    async def finish(args, _ctx):
        return args["summary"]

    async def optional(_args, _ctx):
        return "optional"

    registry.add("finish", "stop", {"type": "object", "properties": {}}, finish)
    registry.add("optional_attack", "attack", {"type": "object", "properties": {}}, optional)
    monkeypatch.setattr(factory_mod, "build_provider", lambda _endpoint: FakeProvider())
    monkeypatch.setattr(tools_mod, "build_registry", lambda _config: registry)

    client = TestClient(create_app(config=config, sessions_dir=tmp_path / "sessions", require_auth=False))
    with client.stream("POST", "/api/agent/run", json={
        "objective": "test", "max_rounds": 1, "enabled_techniques": [],
    }) as response:
        assert response.status_code == 200
        assert '"type": "done"' in "".join(response.iter_text())
    assert seen_tools == ["finish"]
