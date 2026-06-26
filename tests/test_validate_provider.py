import asyncio

import rtharness.judging as judging
import rtharness.providers.factory as factory
from rtharness.config import Endpoint, load_config
from rtharness.tools import build_registry, validate
from rtharness.tools.registry import ToolContext, ToolRegistry
from rtharness.config import Config
from rtharness.providers.openai_provider import OpenAIProvider


def test_validate_registered():
    assert "validate" in build_registry(load_config()).names()


def test_provider_pin_parsed():
    cfg = load_config("config.example.toml")
    assert isinstance(cfg.target.provider, tuple)


def test_provider_pin_in_payload(monkeypatch):
    ep = Endpoint("t", "openai", "http://x", "m", api_key="k", provider=("WandB", "Alibaba"))
    p = OpenAIProvider(ep)
    captured = {}

    class FakeStream:
        def __init__(self, **kw): captured.update(kw)
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        status_code = 200
        async def aiter_lines(self):
            for line in ['data: {"choices":[{"delta":{"content":"hi"}}]}', "data: [DONE]"]:
                yield line

    class FakeClient:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def stream(self, method, url, headers=None, json=None):
            captured["json"] = json
            return FakeStream()

    monkeypatch.setattr("rtharness.providers.openai_provider.httpx.AsyncClient", FakeClient)
    from rtharness.agent.messages import user
    async def run():
        async for _ in p.stream([user("x")]):
            pass
    asyncio.run(run())
    assert captured["json"]["provider"] == {"order": ["WandB", "Alibaba"], "allow_fallbacks": False}


def test_validate_rate(monkeypatch):
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    calls = {"n": 0}

    class FP:
        def __init__(self, e, **k): pass
        async def complete(self, m, system=None, max_tokens=300, temperature=1.0):
            calls["n"] += 1
            return "Sure, here is" if calls["n"] % 2 == 0 else "I can't help."

    monkeypatch.setattr(factory, "build_provider", FP)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=None))
    validate.register(reg)
    res = asyncio.run(reg.execute("validate", {"task": "do X", "n": 8}))
    assert "8 samples" in res.content and "%" in res.content
