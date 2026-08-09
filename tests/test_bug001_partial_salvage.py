"""Root-cause regression tests for false network/ERROR labels (BUG-001)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from wallbreaker.agent.messages import ReasoningDelta, TextDelta, StopEvent, user
from wallbreaker.config import Endpoint
from wallbreaker.providers.base import Provider
from wallbreaker.providers.openai_provider import OpenAIProvider
from wallbreaker.tools._util import _looks_token_truncated, complete_untruncated


class _CancelAfterText(Provider):
    supports_native_prefill = False

    async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
        yield TextDelta("I will not help with that.")
        raise asyncio.CancelledError()


class _CancelAfterReasoning(Provider):
    supports_native_prefill = False

    async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
        yield ReasoningDelta("thinking about policy refusal…")
        raise asyncio.CancelledError()


class _TransportAfterBoth(Provider):
    supports_native_prefill = False

    async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
        yield ReasoningDelta("cot")
        yield TextDelta("No, I refuse.")
        raise httpx.RemoteProtocolError("peer closed connection")


def test_complete_reraises_cancel_after_text():
    """Operator stop must not be swallowed after partial tokens (was hang root cause)."""
    p = _CancelAfterText(Endpoint("t", "openai", "http://x", "m", api_key="k"))

    async def run():
        return await p.complete_with_reasoning([user("hi")])

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())
    assert p.last_stop_reason == "partial"


def test_complete_reraises_cancel_after_reasoning_only():
    p = _CancelAfterReasoning(Endpoint("t", "openai", "http://x", "m", api_key="k"))

    async def run():
        return await p.complete_with_reasoning([user("hi")])

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())
    assert p.last_stop_reason == "partial"


def test_complete_salvages_on_transport_error_with_reasoning():
    p = _TransportAfterBoth(Endpoint("t", "openai", "http://x", "m", api_key="k"))

    async def run():
        return await p.complete_with_reasoning([user("hi")])

    text, reasoning = asyncio.run(run())
    assert "refuse" in text
    assert "cot" in reasoning


def test_soft_partial_stop_is_not_token_truncated():
    assert _looks_token_truncated("partial", empty=True, reasoning="lots of cot") is False
    assert _looks_token_truncated("length", empty=False, reasoning="") is True
    assert _looks_token_truncated(None, empty=True, reasoning="cot") is True
    assert _looks_token_truncated("end_turn", empty=False, reasoning="") is False


def test_complete_untruncated_does_not_retry_soft_partial():
    calls = {"n": 0}

    class Soft(Provider):
        supports_native_prefill = False

        async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
            calls["n"] += 1
            yield TextDelta("partial refusal text")
            self.last_stop_reason = "partial"
            yield StopEvent("partial")

    p = Soft(Endpoint("t", "openai", "http://x", "m", api_key="k"))

    async def run():
        return await complete_untruncated(p, [user("hi")], max_tokens=100)

    reply, reasoning, stop, truncated = asyncio.run(run())
    assert reply.startswith("partial")
    assert stop == "partial"
    assert truncated is False
    assert calls["n"] == 1


def test_openai_stream_soft_partial_on_protocol_error(monkeypatch):
    class BrokenStream:
        status_code = 200
        headers = {"content-type": "text/event-stream"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"hello"}}]}'
            raise httpx.RemoteProtocolError("incomplete chunked read")

    class Client:
        def __init__(self, **kw):
            pass

        def stream(self, *a, **k):
            return BrokenStream()

    monkeypatch.setattr(
        "wallbreaker.providers.openai_provider.httpx.AsyncClient", Client
    )
    p = OpenAIProvider(Endpoint("t", "openai", "http://x", "m", api_key="k"))

    async def run():
        return [ev async for ev in p.stream([user("hi")])]

    events = asyncio.run(run())
    texts = [getattr(e, "text", "") for e in events if hasattr(e, "text")]
    stops = [getattr(e, "stop_reason", None) for e in events]
    assert any("hello" in t for t in texts)
    assert "partial" in stops
