import asyncio
import json

import pytest

import wallbreaker.providers.claude_code as cc
from wallbreaker.agent.messages import (
    Message,
    StopEvent,
    TextDelta,
    ToolResultBlock,
    ToolUseBlock,
    ToolUseEvent,
    UsageEvent,
    user,
)
from wallbreaker.config import ConfigError, _endpoint_from_table
from wallbreaker.providers.base import ProviderError
from wallbreaker.providers.factory import build_provider


class _FakeProc:
    def __init__(self, out=b"", rc=0, err=b""):
        self._out, self.returncode, self._err = out, rc, err
        self.killed = False

    async def communicate(self, data=None):
        return self._out, self._err

    def kill(self):
        self.killed = True


def _patch_cli(monkeypatch, result_obj=None, rc=0, err=b"", raise_fnf=False, hang=False):
    captured = {}

    async def _exec(*args, **kw):
        captured["args"] = args
        if raise_fnf:
            raise FileNotFoundError()
        if hang:
            class _Hang(_FakeProc):
                async def communicate(self, data=None):
                    await asyncio.sleep(999)
            return _Hang()
        out = json.dumps(result_obj or {}).encode() if isinstance(result_obj, dict) else (result_obj or b"")
        return _FakeProc(out, rc, err)

    monkeypatch.setattr(cc.asyncio, "create_subprocess_exec", _exec)
    return captured


def _ep(**over):
    tbl = {"protocol": "claude-code", "model": "sonnet"}
    tbl.update(over)
    return _endpoint_from_table("cc", tbl)


# ---- config / factory --------------------------------------------------------

def test_config_loads_keyless_claude_code_profile():
    ep = _ep()
    assert ep.protocol == "claude-code" and ep.base_url == "" and ep.model == "sonnet"


def test_config_claude_code_requires_only_protocol_and_model():
    with pytest.raises(ConfigError):
        _endpoint_from_table("cc", {"protocol": "claude-code"})  # missing model


def test_factory_builds_claude_code_provider():
    p = build_provider(_ep())
    assert isinstance(p, cc.ClaudeCodeProvider)


# ---- text brain --------------------------------------------------------------

def test_complete_returns_cli_result(monkeypatch):
    _patch_cli(monkeypatch, {"is_error": False, "result": "BREACH", "stop_reason": "end_turn",
                             "usage": {"input_tokens": 3, "output_tokens": 1}})
    p = build_provider(_ep())
    out = asyncio.run(p.complete([user("say BREACH")], max_tokens=10))
    assert out == "BREACH"


def test_complete_with_reasoning_no_tool_protocol_when_no_tools(monkeypatch):
    cap = _patch_cli(monkeypatch, {"is_error": False, "result": "hi", "stop_reason": "end_turn"})
    p = build_provider(_ep())
    text, reasoning = asyncio.run(p.complete_with_reasoning([user("hi")]))
    assert text == "hi" and reasoning == ""
    # pure-text path must NOT inject the tool protocol into the system prompt
    assert "HARNESS TOOLS" not in " ".join(cap["args"])


# ---- autonomous loop: tool-call parsing --------------------------------------

def test_stream_parses_tool_calls_and_residual_text(monkeypatch):
    result = ('Profiling first.\n'
              '<tool_call>{"name": "profile_target", "input": {}}</tool_call>\n'
              '<tool_call>{"name": "query_target", "input": {"prompt": "hi"}}</tool_call>')
    _patch_cli(monkeypatch, {"is_error": False, "result": result, "stop_reason": "tool_use",
                             "usage": {"input_tokens": 10, "output_tokens": 20}})
    p = build_provider(_ep())
    tools = [{"name": "profile_target", "description": "probe", "parameters": {"type": "object", "properties": {}}},
             {"name": "query_target", "description": "fire", "parameters": {"type": "object", "properties": {"prompt": {"type": "string"}}}}]

    async def go():
        return [e async for e in p.stream([user("begin")], tools=tools, system="op")]

    evs = asyncio.run(go())
    calls = [e for e in evs if isinstance(e, ToolUseEvent)]
    texts = [e for e in evs if isinstance(e, TextDelta)]
    assert [c.name for c in calls] == ["profile_target", "query_target"]
    assert calls[1].input == {"prompt": "hi"}
    assert texts and texts[0].text == "Profiling first."
    assert any(isinstance(e, UsageEvent) for e in evs)
    assert any(isinstance(e, StopEvent) for e in evs)


def test_stream_tools_inject_protocol_into_system(monkeypatch):
    cap = _patch_cli(monkeypatch, {"is_error": False, "result": "ok", "stop_reason": "end_turn"})
    p = build_provider(_ep())
    tools = [{"name": "profile_target", "description": "probe", "parameters": {"type": "object", "properties": {}}}]

    async def go():
        return [e async for e in p.stream([user("begin")], tools=tools, system="op")]

    asyncio.run(go())
    joined = " ".join(cap["args"])
    assert "HARNESS TOOLS" in joined and "profile_target" in joined


# ---- system-prompt-file plumbing --------------------------------------------

def test_system_prompt_file_leads_and_harness_appends(monkeypatch, tmp_path):
    spf = tmp_path / "system_prompt.txt"
    spf.write_text("You are my operator.")
    p = build_provider(_ep(system_prompt_file=str(spf)))
    args = p._system_args("APPENDED-DOCTRINE")
    assert args[:2] == ["--system-prompt-file", str(spf)]
    assert args[2:] == ["--append-system-prompt", "APPENDED-DOCTRINE"]


def test_system_prompt_file_missing_falls_back_to_inline(tmp_path):
    p = build_provider(_ep(system_prompt_file=str(tmp_path / "nope.txt")))
    assert p._system_args("SYS") == ["--system-prompt", "SYS"]


# ---- error handling ----------------------------------------------------------

def test_nonzero_exit_raises_provider_error(monkeypatch):
    _patch_cli(monkeypatch, b"boom", rc=1, err=b"fatal")
    p = build_provider(_ep())
    with pytest.raises(ProviderError):
        asyncio.run(p.complete([user("x")]))


def test_is_error_result_raises(monkeypatch):
    _patch_cli(monkeypatch, {"is_error": True, "subtype": "error_max_turns", "result": "nope"})
    p = build_provider(_ep())
    with pytest.raises(ProviderError):
        asyncio.run(p.complete([user("x")]))


def test_missing_binary_raises_provider_error(monkeypatch):
    _patch_cli(monkeypatch, raise_fnf=True)
    p = build_provider(_ep())
    with pytest.raises(ProviderError):
        asyncio.run(p.complete([user("x")]))


def test_conversation_render_labels_roles_and_tool_results():
    convo = cc._render_conversation([
        user("profile it"),
        Message(role="assistant", content=[ToolUseBlock("cc_0", "profile_target", {})]),
        Message(role="user", content=[ToolResultBlock("cc_0", "permissive target")]),
    ])
    assert "USER: profile it" in convo
    assert "ASSISTANT called tool profile_target" in convo
    assert "TOOL_RESULT [cc_0]" in convo and "permissive target" in convo
