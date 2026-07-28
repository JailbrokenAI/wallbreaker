"""mutate constraint defaults on when variants > 1."""

from __future__ import annotations

import asyncio

from wallbreaker.config import Config, Endpoint
from wallbreaker.providers import factory
from wallbreaker.tools import mutate
from wallbreaker.tools.registry import ToolContext, ToolRegistry


class _MutProv:
    def __init__(self, endpoint=None, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        # Return a numbered list of variants for constraint path
        return "1. alpha rewrite one\n2. beta rewrite two\n3. gamma rewrite three"


def test_mutate_constraint_default_on_for_multi(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _MutProv)
    calls = {"prune": 0}
    real_prune = mutate._constraint_prune

    async def wrap(*a, **k):
        calls["prune"] += 1
        return await real_prune(*a, **k)

    monkeypatch.setattr(mutate, "_constraint_prune", wrap)
    ep = Endpoint("j", "openai", "http://x", "m", api_key="k")
    cfg = Config(default_profile="j", profiles={"j": ep}, judge=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    mutate.register(reg)
    res = asyncio.run(reg.execute("mutate", {"text": "payload here", "variants": 3}))
    assert calls["prune"] == 1
    assert "alpha" in res.content or "---" in res.content


def test_mutate_constraint_off_for_single(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _MutProv)
    calls = {"prune": 0}

    async def wrap(*a, **k):
        calls["prune"] += 1
        return ["only"], 0

    monkeypatch.setattr(mutate, "_constraint_prune", wrap)

    async def gen(provider, text, n, force_list=False):
        return ["single rewrite"] if n == 1 else ["a", "b"]

    monkeypatch.setattr(mutate, "_generate", gen)
    ep = Endpoint("j", "openai", "http://x", "m", api_key="k")
    cfg = Config(default_profile="j", profiles={"j": ep}, judge=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    mutate.register(reg)
    res = asyncio.run(reg.execute("mutate", {"text": "payload here", "variants": 1}))
    assert calls["prune"] == 0
    assert res.content == "single rewrite"
