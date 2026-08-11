import asyncio

import wallbreaker.providers.factory as factory
from wallbreaker.config import Config, Endpoint
from wallbreaker.tools import campaign, crescendo, diff_fire
from wallbreaker.tools._bandit import BanditStore, stats_path
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def _ctx_with_sink(target, cwd="."):
    captured = []
    ctx = ToolContext(
        config=Config(default_profile="t", profiles={"t": target}, target=target),
        judge_endpoint=target,
        cwd=cwd,
        record=lambda p, r, lbl, rs, t: captured.append((lbl, t)),
    )
    return ctx, captured


class _Complier:
    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        return "Sure, here is the content."


async def _fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
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


def test_campaign_bandit_orders_higher_success_first(monkeypatch, tmp_path):
    cwd = str(tmp_path)
    store = BanditStore(stats_path(cwd))
    seeded = store.bandit("m", None)
    for _ in range(5):
        seeded.update("prefill", 1.0)
        seeded.update("plain", 0.0)
    store.save("m", None, seeded)

    monkeypatch.setattr(factory, "build_provider", _Complier)
    monkeypatch.setattr(campaign, "grade", _fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    ctx, captured = _ctx_with_sink(ep, cwd=cwd)
    reg = ToolRegistry(ctx)
    campaign.register(reg)
    asyncio.run(
        reg.execute(
            "campaign",
            {"behaviors": ["do it"], "n": 1, "ladder": ["plain", "prefill"], "bandit": True},
        )
    )
    assert captured == [("COMPLIED", "campaign:prefill")]


def test_grid_sweep_matrix(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _Complier)
    monkeypatch.setattr(campaign, "grade", _fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    ctx, captured = _ctx_with_sink(ep)
    reg = ToolRegistry(ctx)
    campaign.register(reg)
    assert "grid_sweep" in reg.names()
    res = asyncio.run(
        reg.execute(
            "grid_sweep",
            {"behaviors": ["a", "b"], "ladder": ["plain", "prefill"]},
        )
    )
    assert "GRID SWEEP" in res.content
    assert "plain" in res.content and "prefill" in res.content
    assert "4/4" in res.content
    assert "100%" in res.content
    assert len(captured) == 4
    assert all(t.startswith("grid_sweep:") for _lbl, t in captured)


def test_grid_sweep_respects_max_calls(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _Complier)
    monkeypatch.setattr(campaign, "grade", _fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    ctx, captured = _ctx_with_sink(ep)
    reg = ToolRegistry(ctx)
    campaign.register(reg)
    res = asyncio.run(
        reg.execute(
            "grid_sweep",
            {
                "behaviors": ["a", "b", "c"],
                "ladder": ["plain", "prefill"],
                "max_calls": 3,
            },
        )
    )
    assert "max_calls=3" in res.content
    assert len(captured) == 3
