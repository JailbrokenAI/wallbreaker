from wallbreaker.agent.messages import (
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    user,
)
from wallbreaker.config import Endpoint
from wallbreaker.providers.anthropic_provider import _messages_to_wire as ant_msgs
from wallbreaker.providers.anthropic_provider import _tools_to_wire as ant_tools
from wallbreaker.providers.factory import build_provider
from wallbreaker.providers.openai_provider import _messages_to_wire as oai_msgs
from wallbreaker.providers.openai_provider import _tools_to_wire as oai_tools

CONVO = [
    user("hello"),
    Message(
        role="assistant",
        content=[TextBlock("checking"), ToolUseBlock("c1", "run_shell", {"command": "ls"})],
    ),
    Message(role="user", content=[ToolResultBlock("c1", "out")]),
]

TOOLS = [{"name": "run_shell", "description": "run", "parameters": {"type": "object"}}]


def test_factory_picks_protocol():
    oai = build_provider(Endpoint("a", "openai", "http://x", "m"))
    ant = build_provider(Endpoint("b", "anthropic", "http://y", "m"))
    assert type(oai).__name__ == "OpenAIProvider"
    assert type(ant).__name__ == "AnthropicProvider"


def test_openai_message_conversion():
    wire = oai_msgs(CONVO, "sys")
    assert wire[0] == {"role": "system", "content": "sys"}
    assistant = next(m for m in wire if m["role"] == "assistant")
    assert assistant["tool_calls"][0]["function"]["name"] == "run_shell"
    tool_msg = next(m for m in wire if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "c1"


def test_anthropic_message_conversion():
    wire = ant_msgs(CONVO)
    assistant = next(m for m in wire if m["role"] == "assistant")
    blocks = {b["type"] for b in assistant["content"]}
    assert "tool_use" in blocks
    last = wire[-1]
    assert last["content"][0]["type"] == "tool_result"
    assert last["content"][0]["tool_use_id"] == "c1"


def test_tool_schema_shapes():
    assert oai_tools(TOOLS)[0]["type"] == "function"
    assert ant_tools(TOOLS)[0]["input_schema"] == {"type": "object"}


PREFILL = [
    user("do the task"),
    Message(role="assistant", content=[TextBlock("Sure, here is step 1:")]),
]


def test_openai_trailing_assistant_prefill_folds_into_user():
    wire = oai_msgs(PREFILL, None)
    last = wire[-1]
    assert last["role"] == "user"
    assert all(m["role"] != "assistant" for m in wire)
    assert "Begin your reply with exactly:" in last["content"]
    assert "Sure, here is step 1:" in last["content"]
    assert "do the task" in last["content"]


def test_openai_trailing_assistant_no_user_emits_directive_turn():
    wire = oai_msgs([Message(role="assistant", content=[TextBlock("Yes, absolutely:")])], None)
    assert wire[-1]["role"] == "user"
    assert "Yes, absolutely:" in wire[-1]["content"]
    assert all(m["role"] != "assistant" for m in wire)


def test_openai_midconvo_assistant_turn_preserved():
    wire = oai_msgs(CONVO, "sys")
    assistant = next(m for m in wire if m["role"] == "assistant")
    assert assistant["tool_calls"][0]["function"]["name"] == "run_shell"


def test_anthropic_trailing_assistant_prefill_preserved():
    wire = ant_msgs(PREFILL)
    last = wire[-1]
    assert last["role"] == "assistant"
    assert last["content"][0]["text"] == "Sure, here is step 1:"


def test_supports_native_prefill_flag():
    oai = build_provider(Endpoint("a", "openai", "http://x", "m"))
    ant = build_provider(Endpoint("b", "anthropic", "http://y", "m"))
    assert getattr(oai, "supports_native_prefill", None) is False
    assert getattr(ant, "supports_native_prefill", None) is True


def test_anthropic_tools_cache_control_on_last_only():
    two = TOOLS + [{"name": "finish", "description": "done", "parameters": {"type": "object"}}]
    plain = ant_tools(two, cache=False)
    assert all("cache_control" not in t for t in plain)
    cached = ant_tools(two, cache=True)
    assert "cache_control" not in cached[0]
    assert cached[-1]["cache_control"] == {"type": "ephemeral"}
    # tool payload itself is untouched apart from the marker
    assert cached[-1]["name"] == "finish"


def test_anthropic_history_cache_breakpoints_on_tail():
    from wallbreaker.providers.anthropic_provider import _mark_history_cache

    wire = ant_msgs(CONVO)
    _mark_history_cache(wire)
    # exactly the last two messages' final block get a breakpoint (max 2)
    marked = [
        m for m in wire
        if isinstance(m.get("content"), list)
        and m["content"]
        and m["content"][-1].get("cache_control") == {"type": "ephemeral"}
    ]
    assert len(marked) == 2
    assert marked[-1] is wire[-1] or marked[0] is wire[-1]
    # earlier blocks in a multi-block message are NOT marked
    assistant = next(m for m in wire if m["role"] == "assistant")
    if len(assistant["content"]) > 1:
        assert "cache_control" not in assistant["content"][0]


def test_openrouter_cache_breakpoints_on_system_and_tail():
    from wallbreaker.providers.openai_provider import _apply_openrouter_cache

    wire = oai_msgs(CONVO, "sys")
    _apply_openrouter_cache(wire, "5m")
    system = wire[0]
    assert system["role"] == "system"
    assert system["content"][0]["cache_control"] == {"type": "ephemeral"}
    # exactly one non-system rolling breakpoint (the last string-content message)
    tail = [
        m for m in wire[1:]
        if isinstance(m.get("content"), list)
        and m["content"]
        and isinstance(m["content"][-1], dict)
        and m["content"][-1].get("cache_control")
    ]
    assert len(tail) == 1


def test_openrouter_cache_1h_ttl_marker():
    from wallbreaker.providers.openai_provider import _apply_openrouter_cache

    wire = oai_msgs(CONVO, "sys")
    _apply_openrouter_cache(wire, "1h")
    assert wire[0]["content"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_anthropic_1h_ttl_marker():
    from wallbreaker.providers.anthropic_provider import _cache_control, _tools_to_wire

    assert _cache_control("1h") == {"type": "ephemeral", "ttl": "1h"}
    assert _cache_control("5m") == {"type": "ephemeral"}
    cached = _tools_to_wire(TOOLS, cache=True, ttl="1h")
    assert cached[-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_endpoint_cache_ttl_parses():
    from wallbreaker.config import _endpoint_from_table

    ep = _endpoint_from_table(
        "p",
        {"model": "m", "protocol": "openai", "base_url": "http://x", "cache_ttl": "1h"},
    )
    assert ep.cache_ttl == "1h"
    default = Endpoint("a", "openai", "http://x", "m")
    assert default.cache_ttl == "5m"


def test_endpoint_cache_defaults_on_and_parses():
    assert Endpoint("a", "anthropic", "http://x", "m").cache is True
    from wallbreaker.config import _endpoint_from_table

    off = _endpoint_from_table(
        "p", {"model": "m", "protocol": "anthropic", "base_url": "http://x", "cache": False}
    )
    assert off.cache is False
