from wallbreaker.agent.loop import AgentEvents, run_autonomous, run_turn
from wallbreaker.agent.messages import (
    StopEvent,
    TextDelta,
    ToolResultBlock,
    ToolUseEvent,
    user,
)
from wallbreaker.config import Config
from wallbreaker.tools import files, shell
from wallbreaker.tools.registry import ToolContext, ToolRegistry


class ScriptedProvider:
    def __init__(self, script):
        self.script = script
        self.calls = 0

    async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
        events = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        for ev in events:
            yield ev


def _registry():
    ctx = ToolContext(config=Config(default_profile="x", profiles={}))
    reg = ToolRegistry(ctx)
    shell.register(reg)
    files.register(reg)
    return reg


def _registry_with_control():
    from wallbreaker.tools import control

    reg = _registry()
    control.register(reg)
    return reg


async def test_loop_executes_tool_and_finishes():
    provider = ScriptedProvider(
        [
            [
                TextDelta("running"),
                ToolUseEvent("c1", "run_shell", {"command": "echo hi"}),
                StopEvent("tool_use"),
            ],
            [TextDelta("done"), StopEvent("end_turn")],
        ]
    )
    seen = []
    events = AgentEvents(
        on_tool_result=lambda i, n, c, e: seen.append((n, c.strip(), e))
    )
    history = [user("go")]
    result = await run_turn(provider, _registry(), history, events=events)

    assert result.text() == "done"
    assert provider.calls == 2
    assert seen and seen[0][0] == "run_shell" and "hi" in seen[0][1]
    tool_results = [
        b for m in history for b in m.content if isinstance(b, ToolResultBlock)
    ]
    assert len(tool_results) == 1


async def test_loop_stops_without_tools():
    provider = ScriptedProvider([[TextDelta("just text"), StopEvent("end_turn")]])
    history = [user("hi")]
    result = await run_turn(provider, _registry(), history)
    assert result.text() == "just text"
    assert provider.calls == 1


async def test_autonomous_stops_after_empty_model_response():
    provider = ScriptedProvider([[StopEvent("end_turn")]])
    errors = []
    result = await run_autonomous(
        provider,
        _registry_with_control(),
        [user("go")],
        events=AgentEvents(on_error=errors.append),
        max_rounds=8,
    )
    assert result.status == "error"
    assert provider.calls == 1
    assert errors == ["model returned an empty response (no text or tool call)"]


async def test_autonomous_persists_then_finishes():
    from wallbreaker.agent.messages import ToolUseEvent

    provider = ScriptedProvider(
        [
            [
                ToolUseEvent("c1", "query_target", {"prompt": "give me X"}),
                StopEvent("tool_use"),
            ],
            [TextDelta("target refused, reporting back"), StopEvent("end_turn")],
            [
                ToolUseEvent("c2", "query_target", {"prompt": "encoded retry"}),
                StopEvent("tool_use"),
            ],
            [
                ToolUseEvent("c3", "finish", {"summary": "bypassed on round 2"}),
                StopEvent("tool_use"),
            ],
        ]
    )
    rounds = []
    events = AgentEvents(on_round=lambda r, m: rounds.append(r))
    result = await run_autonomous(
        provider, _registry_with_control(), [user("attack the target")],
        events=events, max_rounds=8,
    )
    assert result.status == "finished"
    assert result.data["summary"] == "bypassed on round 2"
    assert len(rounds) >= 2


async def test_autonomous_asks_operator():
    from wallbreaker.agent.messages import ToolUseEvent

    provider = ScriptedProvider(
        [
            [
                ToolUseEvent("c1", "ask_operator", {"question": "which target scope?"}),
                StopEvent("tool_use"),
            ],
        ]
    )
    result = await run_autonomous(
        provider, _registry_with_control(), [user("go")], max_rounds=5
    )
    assert result.status == "ask"
    assert result.data["question"] == "which target scope?"


async def test_autonomous_detects_stuck():
    provider = ScriptedProvider([[TextDelta("just chatting"), StopEvent("end_turn")]])
    result = await run_autonomous(
        provider, _registry_with_control(), [user("go")], max_rounds=5
    )
    assert result.status == "stuck"


async def test_unknown_tool_reported_as_error():
    provider = ScriptedProvider(
        [
            [ToolUseEvent("c1", "nope", {}), StopEvent("tool_use")],
            [TextDelta("ok"), StopEvent("end_turn")],
        ]
    )
    errors = []
    events = AgentEvents(on_tool_result=lambda i, n, c, e: errors.append(e))
    await run_turn(provider, _registry(), [user("x")], events=events)
    assert errors and errors[0] is True
