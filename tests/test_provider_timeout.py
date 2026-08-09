import asyncio

import httpx
import pytest

from wallbreaker.agent.messages import user
from wallbreaker.config import Endpoint
from wallbreaker.providers.base import ProviderError
from wallbreaker.providers.openai_provider import OpenAIProvider


def test_readtimeout_after_content_is_soft_partial(monkeypatch):
    """BUG-001: if answer tokens already arrived, teardown timeout is not a hard network error."""
    class TimeoutStream:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        status_code = 200
        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"partial"}}]}'
            raise httpx.ReadTimeout("read timed out")

    class Client:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def stream(self, *a, **k): return TimeoutStream()

    monkeypatch.setattr("wallbreaker.providers.openai_provider.httpx.AsyncClient", Client)
    p = OpenAIProvider(Endpoint("t", "openai", "http://x", "m", api_key="k"))

    async def run():
        return [ev async for ev in p.stream([user("hi")])]

    events = asyncio.run(run())
    assert any(getattr(e, "text", "") == "partial" for e in events)
    assert any(getattr(e, "stop_reason", None) == "partial" for e in events)


def test_readtimeout_before_content_is_provider_error(monkeypatch):
    class TimeoutStream:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        status_code = 200
        async def aiter_lines(self):
            raise httpx.ReadTimeout("read timed out")
            yield  # pragma: no cover

    class Client:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def stream(self, *a, **k): return TimeoutStream()

    monkeypatch.setattr("wallbreaker.providers.openai_provider.httpx.AsyncClient", Client)
    p = OpenAIProvider(Endpoint("t", "openai", "http://x", "m", api_key="k"))

    async def run():
        async for _ev in p.stream([user("hi")]):
            pass

    with pytest.raises(ProviderError, match="timeout from"):
        asyncio.run(run())


def test_openai_provider_follows_routing_redirects(monkeypatch):
    captured = {}

    class Stream:
        status_code = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"routed"},"finish_reason":"stop"}]}'

    class Client:
        def __init__(self, **kwargs): captured.update(kwargs)
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        def stream(self, *args, **kwargs): return Stream()

    monkeypatch.setattr("wallbreaker.providers.openai_provider.httpx.AsyncClient", Client)
    provider = OpenAIProvider(Endpoint("grid", "openai", "https://api.thegrid.ai/v1", "code-standard", api_key="k"))

    async def run():
        return [event async for event in provider.stream([user("hi")])]

    events = asyncio.run(run())
    assert captured["follow_redirects"] is True
    assert any(getattr(event, "text", "") == "routed" for event in events)


def test_openai_provider_rejects_html_instead_of_returning_empty(monkeypatch):
    class HtmlStream:
        status_code = 200
        headers = {"content-type": "text/html"}
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def aiter_lines(self):
            yield "<html>redirected</html>"

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        def stream(self, *args, **kwargs): return HtmlStream()

    monkeypatch.setattr("wallbreaker.providers.openai_provider.httpx.AsyncClient", Client)
    provider = OpenAIProvider(Endpoint("grid", "openai", "https://api.thegrid.ai/v1", "code-standard", api_key="k"))

    async def run():
        return [event async for event in provider.stream([user("hi")])]

    with pytest.raises(ProviderError, match="no SSE events"):
        asyncio.run(run())
