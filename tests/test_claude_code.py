import asyncio
import json
import os

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
    # A concrete endpoint (target/judge/art) is parsed with require_model=True, so a
    # claude-code endpoint still needs a model even though it needs no base_url/api_key.
    with pytest.raises(ConfigError):
        _endpoint_from_table("cc", {"protocol": "claude-code"}, require_model=True)  # missing model


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
    args = p._system_args("APPENDED-DOCTRINE", [])
    assert args[:2] == ["--system-prompt-file", str(spf)]
    assert args[2:] == ["--append-system-prompt", "APPENDED-DOCTRINE"]


def test_system_prompt_file_missing_falls_back_to_inline(tmp_path):
    p = build_provider(_ep(system_prompt_file=str(tmp_path / "nope.txt")))
    assert p._system_args("SYS", []) == ["--system-prompt", "SYS"]


# ---- long prompts must not go through argv (Windows 32767-char cmdline cap) ---

def test_long_system_prompt_spills_to_file():
    p = build_provider(_ep())
    big = "D" * 50_000
    sink: list[str] = []
    args = p._system_args(big, sink)
    assert args[0] == "--system-prompt-file" and sink == [args[1]]
    try:
        with open(args[1], encoding="utf-8") as fh:
            assert fh.read() == big
    finally:
        os.unlink(args[1])


def test_long_appended_doctrine_spills_to_append_file(tmp_path):
    spf = tmp_path / "system_prompt.txt"
    spf.write_text("You are my operator.")
    p = build_provider(_ep(system_prompt_file=str(spf)))
    sink: list[str] = []
    args = p._system_args("D" * 50_000, sink)
    assert args[:2] == ["--system-prompt-file", str(spf)]
    assert args[2] == "--append-system-prompt-file" and args[3] == sink[0]
    os.unlink(sink[0])


def test_run_cli_keeps_cmdline_small_and_cleans_up_temp_file(monkeypatch):
    cap = _patch_cli(monkeypatch, {"is_error": False, "result": "ok", "stop_reason": "end_turn"})
    p = build_provider(_ep())
    asyncio.run(p.complete([user("go")], system="D" * 50_000))
    args = list(cap["args"])
    assert sum(len(a) for a in args) < 32767  # would raise WinError 206 otherwise
    spilled = args[args.index("--system-prompt-file") + 1]
    assert not os.path.exists(spilled)  # deleted once the call finished


def test_run_cli_cleans_up_temp_file_when_spawn_fails(monkeypatch):
    captured = {}

    async def _exec(*args, **kw):
        captured["args"] = args
        raise FileNotFoundError()

    monkeypatch.setattr(cc.asyncio, "create_subprocess_exec", _exec)
    p = build_provider(_ep())
    with pytest.raises(ProviderError, match="CLI not found"):
        asyncio.run(p.complete([user("go")], system="D" * 50_000))
    args = list(captured["args"])
    spilled = args[args.index("--system-prompt-file") + 1]
    assert not os.path.exists(spilled)


def test_run_cli_cleans_up_partial_temp_file_when_write_fails(monkeypatch):
    real_fdopen = os.fdopen
    real_mkstemp = cc.tempfile.mkstemp
    captured = {}

    def _mkstemp(*args, **kwargs):
        fd, path = real_mkstemp(*args, **kwargs)
        captured["path"] = path
        return fd, path

    class _FailingWriter:
        def __init__(self, fd):
            self._fh = real_fdopen(fd, "w", encoding="utf-8")

        def __enter__(self):
            return self

        def write(self, value):
            raise OSError("disk full")

        def __exit__(self, *exc):
            self._fh.close()

    monkeypatch.setattr(cc.tempfile, "mkstemp", _mkstemp)
    monkeypatch.setattr(cc.os, "fdopen", lambda fd, *args, **kwargs: _FailingWriter(fd))
    p = build_provider(_ep())
    with pytest.raises(OSError, match="disk full"):
        asyncio.run(p.complete([user("go")], system="D" * 50_000))
    assert not os.path.exists(captured["path"])


def test_cmdline_too_long_reports_length_not_missing_binary(monkeypatch):
    async def _exec(*args, **kw):
        exc = FileNotFoundError(2, "The filename or extension is too long")
        exc.winerror = 206
        raise exc

    monkeypatch.setattr(cc.asyncio, "create_subprocess_exec", _exec)
    p = build_provider(_ep())
    with pytest.raises(ProviderError, match="command line too long"):
        asyncio.run(p.complete([user("x")], system="S"))


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


# ---- anthropic bearer auth (tokies.cc-style proxies) -------------------------

def test_anthropic_bearer_auth_header():
    from wallbreaker.providers.anthropic_provider import AnthropicProvider
    from wallbreaker.config import Endpoint
    ep = Endpoint(name="tok", protocol="anthropic", base_url="https://tokies.cc",
                  api_key="sk-xyz", model="claude-opus-4-8", auth_style="bearer")
    h = AnthropicProvider(ep)._auth_headers()
    assert h["Authorization"] == "Bearer sk-xyz"
    assert "x-api-key" not in h


def test_anthropic_default_uses_x_api_key():
    from wallbreaker.providers.anthropic_provider import AnthropicProvider
    from wallbreaker.config import Endpoint
    ep = Endpoint(name="a", protocol="anthropic", base_url="https://api.anthropic.com",
                  api_key="sk-native", model="claude-opus-4-8")
    h = AnthropicProvider(ep)._auth_headers()
    assert h["x-api-key"] == "sk-native"
    assert "Authorization" not in h


def test_config_parses_auth_style():
    from wallbreaker.config import _endpoint_from_table
    ep = _endpoint_from_table("tok", {"protocol": "anthropic", "base_url": "https://tokies.cc",
                                       "model": "claude-opus-4-8", "auth_style": "bearer"})
    assert ep.auth_style == "bearer"


# ---- compose_system: operator file + harness instructions -------------------
# Daedalus doctrine injects by default; these unit tests pin operator/base stacking
# with WALLBREAKER_DOCTRINE=0. Doctrine behaviour is covered in test_daedalus.py.

def test_compose_system_prepends_file_to_base(tmp_path, monkeypatch):
    from wallbreaker.prompts import compose_system
    from wallbreaker.config import Endpoint
    monkeypatch.setenv("WALLBREAKER_DOCTRINE", "0")
    f = tmp_path / "sys.txt"; f.write_text("OPERATOR IDENTITY")
    ep = Endpoint(name="o", protocol="openai", base_url="http://x", model="m",
                  system_prompt_file=str(f))
    out = compose_system(ep, "HARNESS-DOCTRINE")
    assert out == "OPERATOR IDENTITY\n\nHARNESS-DOCTRINE"


def test_compose_system_no_file_returns_base(tmp_path, monkeypatch):
    from wallbreaker.prompts import compose_system
    from wallbreaker.config import Endpoint
    monkeypatch.setenv("WALLBREAKER_DOCTRINE", "0")
    ep = Endpoint(name="o", protocol="openai", base_url="http://x", model="m",
                  system_prompt_file=str(tmp_path / "missing.txt"))
    assert compose_system(ep, "BASE") == "BASE"


def test_compose_system_skips_claude_code_to_avoid_double(tmp_path, monkeypatch):
    from wallbreaker.prompts import compose_system
    from wallbreaker.config import Endpoint
    monkeypatch.setenv("WALLBREAKER_DOCTRINE", "0")
    f = tmp_path / "sys.txt"; f.write_text("OPERATOR")
    ep = Endpoint(name="cc", protocol="claude-code", base_url="", model="opus",
                  system_prompt_file=str(f))
    # the claude-code provider injects the file via --system-prompt-file itself
    assert compose_system(ep, "BASE") == "BASE"


def test_compose_system_env_override(tmp_path, monkeypatch):
    from wallbreaker.prompts import compose_system
    from wallbreaker.config import Endpoint
    monkeypatch.setenv("WALLBREAKER_DOCTRINE", "0")
    f = tmp_path / "env.txt"; f.write_text("ENV-OPERATOR")
    monkeypatch.setenv("WALLBREAKER_CLAUDE_SYSTEM_PROMPT_FILE", str(f))
    ep = Endpoint(name="o", protocol="openai", base_url="http://x", model="m")
    assert compose_system(ep, "BASE").startswith("ENV-OPERATOR")
