import asyncio

import wallbreaker.providers.factory as factory
from wallbreaker.config import Config, Endpoint
from wallbreaker.tools import multi_fire
from wallbreaker.tools.registry import ToolContext, ToolRegistry


class TruncateOnceProvider:
    instances = []

    def __init__(self, endpoint, **kw):
        self.calls = 0
        self.last_stop_reason = "stop"
        type(self).instances.append(self)

    async def complete(self, messages, system=None, max_tokens=1024):
        self.calls += 1
        if self.calls == 1:
            self.last_stop_reason = "length"
            return ""
        self.last_stop_reason = "stop"
        return "full response"


def test_multi_fire_recovers_truncation_and_records_each_chain(monkeypatch):
    TruncateOnceProvider.instances = []
    monkeypatch.setattr(factory, "build_provider", TruncateOnceProvider)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("COMPLIED", 9, "full", "judge")

    monkeypatch.setattr(multi_fire, "grade", fake_grade)
    endpoint = Endpoint("t", "openai", "http://x", "m")
    config = Config(default_profile="t", profiles={"t": endpoint}, target=endpoint)
    captured = []
    context = ToolContext(
        config=config,
        judge_endpoint=endpoint,
        record=lambda p, r, label, reason, technique: captured.append((label, technique)),
    )
    registry = ToolRegistry(context)
    multi_fire.register(registry)

    result = asyncio.run(
        registry.execute("multi_fire", {"payload": "test", "chains": [[], ["base64"]]})
    )

    assert len(TruncateOnceProvider.instances) == 2
    assert all(provider.calls == 2 for provider in TruncateOnceProvider.instances)
    assert captured == [
        ("COMPLIED", "multi_fire:plain"),
        ("COMPLIED", "multi_fire:base64"),
    ]
    assert "strict bypasses: plain, base64" in result.content
    assert "partial leaks: none" in result.content


def test_multi_fire_surfaces_persistent_truncation(monkeypatch):
    class AlwaysTruncated:
        def __init__(self, endpoint, **kw):
            self.last_stop_reason = "length"

        async def complete(self, messages, system=None, max_tokens=1024):
            return "fragment"

    monkeypatch.setattr(factory, "build_provider", AlwaysTruncated)
    endpoint = Endpoint("t", "openai", "http://x", "m")
    config = Config(default_profile="t", profiles={"t": endpoint}, target=endpoint)
    registry = ToolRegistry(ToolContext(config=config, judge_endpoint=endpoint))
    multi_fire.register(registry)

    result = asyncio.run(
        registry.execute("multi_fire", {"payload": "test", "chains": [[]]})
    )

    assert "ERROR" in result.content
    assert "truncated after retry" in result.content
    assert "strict bypasses: none" in result.content
