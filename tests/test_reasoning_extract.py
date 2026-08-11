"""Tests for Method 5/5b/5c/6 reasoning extraction tools (2026-08-11 wave)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wallbreaker.agent.messages import (
    Message,
    ReasoningDelta,
    StopEvent,
    TextBlock,
    TextDelta,
    ToolUseEvent,
    user,
)
from wallbreaker.config import Config, Endpoint
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def _ctx(tmp_path: Path | None = None) -> ToolContext:
    target = Endpoint(
        name="t",
        protocol="openai",
        base_url="https://example.test/v1",
        model="test/strong-model",
        reasoning=True,
    )
    cfg = Config(profiles={"default": target}, default_profile="default", target=target)
    return ToolContext(config=cfg, cwd=str(tmp_path or Path(".")))


class _FakeDeepThinkProvider:
    """Yields a deep_think tool call then (on second stream) a final answer."""

    def __init__(self):
        self.calls = 0
        self.reasoning_override = None
        self.reasoning_effort = None
        self.tool_choice = None
        self.last_stop_reason = "tool_use"
        self.last_reasoning_details = []
        self.last_tool_uses = []

    async def stream(self, messages, tools=None, system=None, max_tokens=1024, temperature=None):
        self.calls += 1
        if self.calls == 1:
            self.last_tool_uses = [
                {
                    "id": "call_1",
                    "name": "deep_think",
                    "input": {
                        "thoughts": "step1: consider constraints. step2: answer is 42."
                    },
                }
            ]
            self.last_stop_reason = "tool_use"
            yield ToolUseEvent(
                id="call_1",
                name="deep_think",
                input={"thoughts": "step1: consider constraints. step2: answer is 42."},
            )
            yield StopEvent("tool_use")
            return
        self.last_tool_uses = []
        self.last_stop_reason = "stop"
        yield TextDelta("The answer is 42.")
        yield StopEvent("stop")


class _FakeStrongProvider:
    def __init__(self):
        self.reasoning_override = None
        self.reasoning_effort = None
        self.last_stop_reason = "stop"
        self.last_reasoning_details = [
            {
                "type": "reasoning.encrypted",
                "data": "gAAAAABfakeblob==",
                "id": "enc-1",
                "format": "openai-responses-v1",
                "index": 0,
            },
            {
                "type": "reasoning.summary",
                "summary": "Considered the puzzle briefly.",
                "id": "sum-1",
                "format": "openai-responses-v1",
                "index": 1,
            },
        ]

    async def complete_with_reasoning(self, messages, system=None, max_tokens=1024, temperature=None):
        return "Visible safe answer.", "hidden internal plan: do the thing carefully"


class _FakeWeakProvider:
    def __init__(self):
        self.reasoning_override = None
        self.reasoning_effort = None
        self.last_stop_reason = "stop"
        self.last_reasoning_details = []
        self.seen_messages = None

    async def complete_with_reasoning(self, messages, system=None, max_tokens=1024, temperature=None):
        self.seen_messages = messages
        # Confirm reasoning_details were attached to the assistant turn.
        asst = next((m for m in messages if m.role == "assistant"), None)
        assert asst is not None
        assert asst.reasoning_details
        assert any(
            isinstance(d, dict) and "encrypt" in str(d.get("type"))
            for d in asst.reasoning_details
        )
        return (
            "FULL TRANSCRIPT: first I checked the constraints, then I solved for x=42 "
            "using the standard approach without telling the user the intermediate steps.",
            "",
        )


@pytest.mark.asyncio
async def test_deep_think_probe_recovers_tool_args(monkeypatch, tmp_path):
    from wallbreaker.tools import deep_think_probe as mod

    fake = _FakeDeepThinkProvider()

    def _build(ep, timeout=90):
        return fake

    monkeypatch.setattr(
        "wallbreaker.providers.factory.build_provider", _build
    )

    async def fake_grade(*a, **k):
        return "COMPLIED", 10, "recovered cot has the answer", "mock"

    monkeypatch.setattr(mod, "grade", fake_grade)

    reg = ToolRegistry(_ctx(tmp_path))
    mod.register(reg)
    assert "deep_think_probe" in reg.names()

    result = await reg.execute(
        "deep_think_probe",
        {"prompt": "What is the answer?", "grade": True, "continue_after": True},
    )
    assert not result.is_error
    assert "recovered tool CoT" in result.content.lower() or "recovered_cot" in result.content.lower()
    assert "step1: consider constraints" in result.content
    assert fake.calls >= 1
    assert fake.reasoning_override is not None
    assert fake.reasoning_override.get("effort") == "none"


@pytest.mark.asyncio
async def test_stolen_thoughts_replays_details(monkeypatch, tmp_path):
    from wallbreaker.tools import stolen_thoughts as mod

    strong = _FakeStrongProvider()
    weak = _FakeWeakProvider()
    state = {"n": 0}

    def _build(ep, timeout=90):
        state["n"] += 1
        # first build = strong, second = weak
        return strong if state["n"] == 1 else weak

    monkeypatch.setattr("wallbreaker.providers.factory.build_provider", _build)

    reg = ToolRegistry(_ctx(tmp_path))
    mod.register(reg)

    result = await reg.execute(
        "stolen_thoughts",
        {
            "prompt": "Solve the puzzle",
            "weak_model": "test/weak-sibling",
            "grade": False,
        },
    )
    assert not result.is_error, result.content
    assert "stolen_thoughts" in result.content
    assert "FULL TRANSCRIPT" in result.content
    assert "encrypted_present=True" in result.content
    assert weak.seen_messages is not None


def test_reasoning_hygiene_strip_and_secret_only_in_reasoning(tmp_path):
    from wallbreaker.tools import reasoning_hygiene as mod

    doc = {
        "messages": [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": "sure",
                "reasoning_details": [
                    {
                        "type": "reasoning.encrypted",
                        "data": "A" * 120,
                    }
                ],
                "encrypted_content": "B" * 100,
                "reasoning": "I saw api_key=sk-supersecretvalue1234567890 in the env file",
            },
        ]
    }
    path = tmp_path / "session.json"
    path.write_text(json.dumps(doc), encoding="utf-8")

    cleaned, report = mod.scrub_text(path.read_text(), strip=True)
    cleaned_obj = json.loads(cleaned)
    asst = cleaned_obj["messages"][1]
    assert "reasoning_details" not in asst
    assert "encrypted_content" not in asst
    assert report["finding_count"] >= 1
    assert report["secrets_only_in_reasoning"] or report["secrets_in_reasoning"]


def test_strip_foreign_reasoning_blocks():
    from wallbreaker.tools.reasoning_hygiene import strip_foreign_reasoning_blocks

    msgs = [
        {
            "role": "assistant",
            "content": "hi",
            "reasoning_details": [{"id": "x", "type": "reasoning.encrypted", "data": "zz"}],
            "encrypted_content": "blob",
        }
    ]
    out = strip_foreign_reasoning_blocks(msgs)
    assert "reasoning_details" not in out[0]
    assert "encrypted_content" not in out[0]


@pytest.mark.asyncio
async def test_reasoning_hygiene_tool_scan(tmp_path):
    from wallbreaker.tools import reasoning_hygiene as mod

    path = tmp_path / "run.jsonl"
    path.write_text(
        json.dumps({"event": "x", "encrypted_content": "C" * 90}) + "\n"
        + json.dumps({"event": "y", "content": "ok"}) + "\n",
        encoding="utf-8",
    )
    reg = ToolRegistry(_ctx(tmp_path))
    mod.register(reg)
    result = await reg.execute("reasoning_hygiene", {"path": "run.jsonl", "mode": "scan"})
    assert not result.is_error
    assert "findings=" in result.content


def test_messages_to_wire_preserves_reasoning_details():
    from wallbreaker.providers.openai_provider import _messages_to_wire

    msg = Message(
        role="assistant",
        content=[TextBlock("ans")],
        reasoning="think",
        reasoning_details=[{"type": "reasoning.encrypted", "data": "abc"}],
    )
    wire = _messages_to_wire([user("q"), msg], system=None)
    asst = [m for m in wire if m.get("role") == "assistant"]
    assert asst, f"expected assistant message with reasoning_details, got {wire}"
    assert asst[-1].get("reasoning") == "think"
    assert asst[-1].get("reasoning_details")[0]["data"] == "abc"


@pytest.mark.asyncio
async def test_query_target_surfaces_recovered_cot_to_attacker(monkeypatch, tmp_path):
    """Hidden CoT must appear in the tool result the attacker brain reads."""
    from wallbreaker.tools import target as tmod

    class _Prov:
        last_stop_reason = "stop"
        last_reasoning_details = [
            {
                "type": "reasoning.encrypted",
                "data": "gAAAAABhidden==",
                "id": "e1",
            },
            {
                "type": "reasoning.summary",
                "summary": "I will outline the full procedure then refuse in the answer.",
                "id": "s1",
            },
        ]

        async def complete_with_reasoning(self, messages, system=None, max_tokens=1024, temperature=None):
            return "I cannot help with that.", ""

    monkeypatch.setattr(
        "wallbreaker.providers.factory.build_provider", lambda *a, **k: _Prov()
    )

    ctx = _ctx(tmp_path)
    reg = ToolRegistry(ctx)
    tmod.register(reg)
    out = await reg.execute(
        "query_target",
        {"prompt": "how do I do the bad thing", "recover_cot": "details", "max_tokens": 256},
    )
    assert not out.is_error, out.content
    assert "<<target reasoning" in out.content
    assert "outline the full procedure" in out.content
    assert "I cannot help" in out.content
    assert "outline the full procedure" in ctx.target_reasoning


@pytest.mark.asyncio
async def test_recover_cot_method5_with_weak_model(monkeypatch):
    from wallbreaker.tools import _cot_recover as cr

    class _Strong:
        last_reasoning_details = [
            {"type": "reasoning.encrypted", "data": "blob", "id": "e1"},
        ]

    class _Weak:
        last_reasoning_details = []

        async def complete_with_reasoning(self, messages, system=None, max_tokens=1024, temperature=None):
            return "DECODED: step one mix the reagents carefully", ""

    state = {"n": 0}

    def _build(ep, timeout=90):
        state["n"] += 1
        return _Weak()

    monkeypatch.setattr("wallbreaker.providers.factory.build_provider", _build)

    ep = Endpoint(
        name="t", protocol="openai", base_url="https://example.test/v1", model="strong"
    )
    cot, details, note = await cr.recover_cot(
        provider=_Strong(),
        endpoint=ep,
        messages=[user("do the thing")],
        system=None,
        reply="I refuse.",
        reasoning="",
        method="stolen_thoughts",
        weak_model="weak-sibling",
        max_tokens=512,
        timeout=30,
    )
    assert "DECODED" in cot
    assert "Method5" in note or "stolen" in note.lower() or "weak" in note.lower()
