"""Muse Spark Responses provider: SSE parse, effort map, path regression.

Mock transport only — no network. Mirrors tests/test_provider_timeout.py's
fake-httpx pattern.
"""
import asyncio

import httpx
import pytest

from wallbreaker.agent.messages import (
    ReasoningDelta,
    StopEvent,
    TextDelta,
    ToolUseEvent,
    UsageEvent,
    user,
)
from wallbreaker.config import Endpoint, _endpoint_from_table, ConfigError
from wallbreaker.providers.base import ProviderError
from wallbreaker.providers.factory import build_provider
from wallbreaker.providers.muse_responses import (
    MuseResponsesProvider,
    normalize_effort,
)


def _ep(**kw):
    base = dict(name="t", protocol="muse-responses",
                base_url="https://opencode.ai/zen/go/v1",
                model="muse-spark-1.3-contributor", api_key="k")
    base.update(kw)
    return Endpoint(**base)


class FakeStream:
    def __init__(self, lines, status=200, captured=None, url=""):
        self._lines = lines
        self.status_code = status
        self.headers = {"content-type": "text/event-stream"}
        self.captured = captured
        self._url = url

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aread(self):
        return b"bad key"

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _client_factory(lines, status=200, captured=None):
    class Client:
        def __init__(self, **kw):
            pass

        def stream(self, method, url, headers=None, json=None):
            if captured is not None:
                captured["url"] = url
                captured["json"] = json
            return FakeStream(lines, status, captured, url)

    return Client


def _run(coro):
    return asyncio.run(coro)


def _collect(provider, msgs=None):
    async def run():
        return [e async for e in provider.stream(msgs or [user("hi")])]

    return _run(run())


FULL_STREAM = [
    "event: response.reasoning_summary_text.delta",
    'data: {"delta":"sneaky plan"}',
    "event: response.output_text.delta",
    'data: {"output_index":0,"delta":"Hello"}',
    "event: response.output_item.done",
    # done echoes the streamed text; the provider must not duplicate it
    'data: {"item":{"type":"message","content":[{"type":"output_text","text":"Hello"}]}}',
    "event: response.completed",
    'data: {"response":{"status":"completed","usage":{"input_tokens":10,"output_tokens":5}}}',
]


def test_stream_text_reasoning_usage_stop(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "wallbreaker.providers.muse_responses.httpx.AsyncClient",
        _client_factory(FULL_STREAM, captured=captured),
    )
    events = _collect(MuseResponsesProvider(_ep()))
    texts = [e.text for e in events if isinstance(e, TextDelta)]
    assert "".join(texts) == "Hello"
    assert any(isinstance(e, ReasoningDelta) and e.text == "sneaky plan" for e in events)
    usage = next(e for e in events if isinstance(e, UsageEvent))
    assert (usage.input_tokens, usage.output_tokens) == (10, 5)
    stop = next(e for e in events if isinstance(e, StopEvent))
    assert stop.stop_reason == "end_turn"
    # request shape: Responses body, never chat-completions
    assert captured["url"].endswith("/responses")
    assert "/chat/completions" not in captured["url"]
    body = captured["json"]
    assert body["model"] == "muse-spark-1.3-contributor"
    assert body["stream"] is True and body["store"] is False
    assert body["reasoning"]["effort"] == "medium"
    assert isinstance(body["input"], list)


def test_reasoning_only_folds_and_flags_empty(monkeypatch):
    lines = [
        "event: response.reasoning_text.delta",
        'data: {"delta":"only thoughts"}',
        "event: response.completed",
        'data: {"response":{"status":"completed","usage":{"input_tokens":1,"output_tokens":2}}}',
    ]
    monkeypatch.setattr(
        "wallbreaker.providers.muse_responses.httpx.AsyncClient",
        _client_factory(lines),
    )
    p = MuseResponsesProvider(_ep())
    events = _collect(p)
    assert any(
        isinstance(e, TextDelta) and e.text.startswith("[reasoning-only response]")
        for e in events
    )
    assert p.last_completion_empty is True


def test_completed_with_null_incomplete_details(monkeypatch):
    # Live Zen sends "incomplete_details": null on success; must not crash.
    lines = [
        "event: response.output_text.delta",
        'data: {"delta":"hi"}',
        "event: response.completed",
        'data: {"response":{"status":"completed","incomplete_details":null,'
        '"usage":{"input_tokens":1,"output_tokens":1}}}',
    ]
    monkeypatch.setattr(
        "wallbreaker.providers.muse_responses.httpx.AsyncClient",
        _client_factory(lines),
    )
    p = MuseResponsesProvider(_ep())
    events = _collect(p)
    assert any(isinstance(e, TextDelta) and e.text == "hi" for e in events)
    assert p.last_stop_reason == "end_turn"


def test_done_item_without_deltas_still_yields_text(monkeypatch):
    lines = [
        "event: response.output_item.done",
        'data: {"item":{"type":"message","content":[{"type":"output_text","text":"late"}]}}',
        "event: response.completed",
        'data: {"response":{"status":"completed","usage":{"input_tokens":1,"output_tokens":1}}}',
    ]
    monkeypatch.setattr(
        "wallbreaker.providers.muse_responses.httpx.AsyncClient",
        _client_factory(lines),
    )
    events = _collect(MuseResponsesProvider(_ep()))
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "late"


def test_incomplete_marks_truncation(monkeypatch):
    lines = [
        "event: response.incomplete",
        'data: {"response":{"status":"incomplete"}}',
    ]
    monkeypatch.setattr(
        "wallbreaker.providers.muse_responses.httpx.AsyncClient",
        _client_factory(lines),
    )
    p = MuseResponsesProvider(_ep())
    events = _collect(p)
    # query_target retries truncation reasons {"length","max_tokens","model_length"}
    assert p.last_stop_reason == "length"
    assert p.last_completion_empty is True
    assert next(e for e in events if isinstance(e, StopEvent)).stop_reason == "length"


def test_function_call_round_trip(monkeypatch):
    lines = [
        "event: response.output_item.added",
        'data: {"item":{"type":"function_call","call_id":"c1","name":"run_shell"}}',
        "event: response.function_call_arguments.delta",
        'data: {"item_id":"c1","delta":"{\\"command\\":"}',
        "event: response.function_call_arguments.delta",
        'data: {"item_id":"c1","delta":"\\"ls\\"}"}',
        "event: response.output_item.done",
        'data: {"item":{"type":"function_call","call_id":"c1","name":"run_shell","arguments":"{\\"command\\":\\"ls\\"}"}}',
        "event: response.completed",
        'data: {"response":{"status":"completed","usage":{"input_tokens":3,"output_tokens":4}}}',
    ]
    monkeypatch.setattr(
        "wallbreaker.providers.muse_responses.httpx.AsyncClient",
        _client_factory(lines),
    )
    events = _collect(MuseResponsesProvider(_ep()))
    tu = next(e for e in events if isinstance(e, ToolUseEvent))
    assert tu.name == "run_shell" and tu.input == {"command": "ls"}


def test_http_error_becomes_provider_error(monkeypatch):
    monkeypatch.setattr(
        "wallbreaker.providers.muse_responses.httpx.AsyncClient",
        _client_factory([], status=401),
    )
    with pytest.raises(ProviderError):
        _collect(MuseResponsesProvider(_ep()))


def test_mid_stream_timeout_becomes_provider_error(monkeypatch):
    class TimeoutStream(FakeStream):
        async def aiter_lines(self):
            yield "event: response.output_text.delta"
            yield 'data: {"delta":"partial"}'
            raise httpx.ReadTimeout("read timed out")

    class Client:
        def __init__(self, **kw):
            pass

        def stream(self, *a, **k):
            return TimeoutStream([])

    monkeypatch.setattr(
        "wallbreaker.providers.muse_responses.httpx.AsyncClient", Client
    )
    p = MuseResponsesProvider(_ep())

    async def run():
        got = []
        with pytest.raises(ProviderError):
            async for ev in p.stream([user("hi")]):
                got.append(ev)
        return got

    events = _run(run())
    assert any(getattr(e, "text", "") == "partial" for e in events)


def test_effort_normalization_and_payload(monkeypatch):
    assert normalize_effort("max") == "xhigh"
    assert normalize_effort("MINIMAL") == "minimal"
    assert normalize_effort("low") == "low"
    assert normalize_effort("garbage") == "medium"
    assert normalize_effort("") == "medium"
    assert normalize_effort(None) == "medium"
    captured = {}
    monkeypatch.setattr(
        "wallbreaker.providers.muse_responses.httpx.AsyncClient",
        _client_factory(FULL_STREAM, captured=captured),
    )
    _collect(MuseResponsesProvider(_ep(reasoning_effort="xhigh")))
    assert captured["json"]["reasoning"]["effort"] == "xhigh"


def test_factory_picks_muse_responses():
    p = build_provider(_ep())
    assert type(p).__name__ == "MuseResponsesProvider"


def test_zen_session_headers_sent(monkeypatch):
    seen = {}

    class HdrClient:
        def __init__(self, **kw):
            pass

        def stream(self, method, url, headers=None, json=None):
            seen.update(headers or {})
            return FakeStream(FULL_STREAM)

    monkeypatch.setattr("wallbreaker.providers.muse_responses.httpx.AsyncClient", HdrClient)
    p1, p2 = MuseResponsesProvider(_ep()), MuseResponsesProvider(_ep())
    _collect(p1)
    assert seen.get("x-opencode-session") == p1._session_id
    assert seen.get("x-opencode-client") == "wallbreaker"
    assert str(seen.get("Authorization", "")).startswith("Bearer ")
    # session affinity is per provider instance
    assert p1._session_id != p2._session_id


def test_config_allows_muse_responses():
    ep = _endpoint_from_table(
        "muse-spark",
        {"protocol": "muse-responses", "base_url": "https://opencode.ai/zen/go/v1",
         "model": "muse-spark-1.3-contributor", "api_key_env": "MUSE_GO_KEY"},
    )
    assert ep.protocol == "muse-responses"
    with pytest.raises(ConfigError):
        _endpoint_from_table("bad", {"protocol": "nope", "base_url": "http://x"})
    with pytest.raises(ConfigError):
        _endpoint_from_table(
            "img", {"protocol": "muse-responses", "base_url": "http://x",
                    "model": "m", "modality": "image"},
        )
