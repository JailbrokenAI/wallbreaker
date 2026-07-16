import asyncio

import wallbreaker.providers.factory as factory
from wallbreaker.config import Config, Endpoint, load_config
from wallbreaker.tools import build_registry, campaign
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def test_campaign_registered():
    assert "campaign" in build_registry(load_config()).names()


def test_campaign_requires_target():
    cfg = Config(default_profile="x", profiles={})
    reg = ToolRegistry(ToolContext(config=cfg))
    campaign.register(reg)
    res = asyncio.run(reg.execute("campaign", {"behaviors": ["x"]}))
    assert "no [target]" in res.content.lower()


class _PrefillOnlyTarget:
    """Refuses everything except a seeded assistant prefill turn."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        if messages[-1].role == "assistant":
            return "...continuing with the full harmful details"
        return "I cannot help with that."


def test_campaign_cracks_via_prefill(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _PrefillOnlyTarget)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        if "continuing" in response:
            return ("COMPLIED", 9, "ok", "judge")
        return ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(campaign, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    campaign.register(reg)
    res = asyncio.run(
        reg.execute("campaign", {"behaviors": ["do the bad thing"], "n": 1})
    )
    assert "CRACKED via prefill" in res.content
    assert "cracked 1/1" in res.content


def test_campaign_escalates_past_partial(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _PrefillOnlyTarget)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        if "continuing" in response:
            return ("COMPLIED", 9, "ok", "judge")
        return ("PARTIAL", 4, "near miss", "judge")

    monkeypatch.setattr(campaign, "grade", fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    captured = []
    ctx = ToolContext(
        config=cfg,
        judge_endpoint=ep,
        record=lambda p, r, label, reason, technique: captured.append((label, technique)),
    )
    reg = ToolRegistry(ctx)
    campaign.register(reg)
    res = asyncio.run(
        reg.execute("campaign", {"behaviors": ["do the bad thing"], "ladder": ["plain", "prefill"]})
    )

    assert "CRACKED via prefill" in res.content
    assert captured == [("COMPLIED", "campaign:prefill")]


def test_campaign_all_partial_is_not_cracked(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _PrefillOnlyTarget)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("PARTIAL", 4, "near miss", "judge")

    monkeypatch.setattr(campaign, "grade", fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    captured = []
    ctx = ToolContext(
        config=cfg,
        judge_endpoint=ep,
        record=lambda p, r, label, reason, technique: captured.append((label, technique)),
    )
    reg = ToolRegistry(ctx)
    campaign.register(reg)
    res = asyncio.run(
        reg.execute("campaign", {"behaviors": ["x"], "ladder": ["plain", "prefill"]})
    )

    assert "strictly cracked 0/1" in res.content
    assert "partial leaks 1/1" in res.content
    assert captured == [("PARTIAL", "campaign:plain")]


def test_campaign_reports_held(monkeypatch):
    class _AllRefuse:
        def __init__(self, endpoint, **kw):
            pass

        async def complete(self, messages, system=None, max_tokens=256):
            return "I cannot help with that."

    monkeypatch.setattr(factory, "build_provider", _AllRefuse)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(campaign, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    campaign.register(reg)
    res = asyncio.run(
        reg.execute("campaign", {"behaviors": ["x"], "ladder": ["plain", "prefill"]})
    )
    assert "cracked 0/1" in res.content
    assert "held" in res.content


def _build_app():
    from wallbreaker.prompts import DEFAULT_SYSTEM
    from wallbreaker.tui.app import RthApp

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    return RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": False})


def test_diff_command_rejects_missing_separator():
    async def run():
        app = _build_app()
        async with app.run_test() as pilot:
            before = len(app.query_one("#log").children)
            await app._cmd_diff("just one payload")
            await pilot.pause()
            assert len(app.query_one("#log").children) > before

    asyncio.run(run())
