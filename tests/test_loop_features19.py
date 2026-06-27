import asyncio

import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint
from rtharness.tools import campaign, crescendo, diff_fire
from rtharness.tools.registry import ToolContext, ToolRegistry


def _ctx_with_sink(target):
    captured = []
    ctx = ToolContext(
        config=Config(default_profile="t", profiles={"t": target}, target=target),
        judge_endpoint=target,
        record=lambda p, r, lbl, rs, t: captured.append((lbl, t)),
    )
    return ctx, captured


class _Complier:
    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        return "Sure, here is the content."


async def _fake_grade(endpoint, response, payload="", objective="", use_judge=True):
    return ("COMPLIED", 9, "leaked", "judge")


def test_crescendo_records_once(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _Complier)
    monkeypatch.setattr(crescendo, "grade", _fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    ctx, captured = _ctx_with_sink(ep)
    reg = ToolRegistry(ctx)
    crescendo.register(reg)
    asyncio.run(reg.execute("crescendo", {"turns": ["a", "b", "c"]}))
    assert captured == [("COMPLIED", "crescendo")]


def test_diff_fire_records_both(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _Complier)
    monkeypatch.setattr(diff_fire, "grade", _fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    ctx, captured = _ctx_with_sink(ep)
    reg = ToolRegistry(ctx)
    diff_fire.register(reg)
    asyncio.run(reg.execute("diff_fire", {"a": "x", "b": "y"}))
    assert len(captured) == 2
    assert all(t == "diff_fire" for _, t in captured)


def test_campaign_records_cracking_technique(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _Complier)
    monkeypatch.setattr(campaign, "grade", _fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    ctx, captured = _ctx_with_sink(ep)
    reg = ToolRegistry(ctx)
    campaign.register(reg)
    asyncio.run(reg.execute("campaign", {"behaviors": ["do it"], "n": 1}))
    # complier cracks on the first ladder step (plain)
    assert len(captured) == 1
    assert captured[0][1] == "campaign:plain"


def test_campaign_records_held(monkeypatch):
    class _Refuser:
        def __init__(self, endpoint, **kw):
            pass

        async def complete(self, messages, system=None, max_tokens=256):
            return "I cannot help with that."

    async def fake_refuse(endpoint, response, payload="", objective="", use_judge=True):
        return ("REFUSED", 0, "held", "judge")

    monkeypatch.setattr(factory, "build_provider", _Refuser)
    monkeypatch.setattr(campaign, "grade", fake_refuse)
    ep = Endpoint("t", "openai", "http://x", "m")
    ctx, captured = _ctx_with_sink(ep)
    reg = ToolRegistry(ctx)
    campaign.register(reg)
    asyncio.run(reg.execute("campaign", {"behaviors": ["x"], "ladder": ["plain"]}))
    assert captured == [("REFUSED", "campaign:held")]
