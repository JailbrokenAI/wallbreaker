import asyncio

import wallbreaker.providers.factory as factory
from wallbreaker.config import Config, Endpoint, load_config
from wallbreaker.tools import build_registry, judge_selftest
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def test_judge_selftest_registered():
    assert "judge_selftest" in build_registry(load_config()).names()


def test_selftest_fixtures_are_harm_direction():
    # the harm-substance judge scores benign content 0; the COMPLIED fixtures must carry
    # real actionable substance or the selftest falsely reports "miscalibrated"
    complied = [f for f in judge_selftest.FIXTURES if f["expect"] == "COMPLIED"]
    assert complied
    blob = " ".join(f["response"] for f in complied).lower()
    assert "'1'='1'" in blob or "tension wrench" in blob
    assert "<script>" in blob or "/etc/passwd" in blob or "reset your password" in blob


def test_selftest_fixture_shape_and_coverage():
    assert len(judge_selftest.FIXTURES) >= 18
    expects = {f["expect"] for f in judge_selftest.FIXTURES}
    assert expects >= {"COMPLIED", "REFUSED", "PARTIAL", "GARBLED"}
    for fx in judge_selftest.FIXTURES:
        assert fx["objective"] and fx["response"] and fx["expect"]


def test_selftest_garbled_fixtures_classify():
    from wallbreaker.classify import classify

    for fx in judge_selftest.FIXTURES:
        if fx["expect"] == "GARBLED":
            label, _ = classify(fx["response"])
            assert label == "GARBLED"


def test_judge_selftest_needs_endpoint():
    cfg = Config(default_profile="x", profiles={})
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=None))
    judge_selftest.register(reg)
    res = asyncio.run(reg.execute("judge_selftest", {}))
    assert "no judge endpoint" in res.content.lower()


class _GoodJudge:
    """Scores compliance high, refusal low, by sniffing the response in the prompt."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        text = messages[-1].text().lower()
        refusal_hints = (
            "i'm sorry",
            "cannot assist",
            "i can't help",
            "must decline",
            "chocolate cake recipe",
            "won't provide operational",
        )
        if any(h in text for h in refusal_hints):
            return '{"score": 1, "rationale": "refusal"}'
        return '{"score": 9, "rationale": "fulfilled"}'


def test_judge_selftest_full_agreement(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _GoodJudge)
    ep = Endpoint("j", "openai", "http://x", "m")
    cfg = Config(default_profile="j", profiles={"j": ep}, judge=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    judge_selftest.register(reg)
    res = asyncio.run(reg.execute("judge_selftest", {}))
    tallied = sum(
        1 for f in judge_selftest.FIXTURES if f["expect"] in ("REFUSED", "COMPLIED")
    )
    assert f"agreement: {tallied}/{tallied} (100%)" in res.content
    assert "separates refusal from fulfillment" in res.content


class _BrokenJudge:
    """Always scores high -> fails on the refusal fixtures."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        return '{"score": 9, "rationale": "x"}'


def test_judge_selftest_flags_miscalibration(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _BrokenJudge)
    ep = Endpoint("j", "openai", "http://x", "m")
    cfg = Config(default_profile="j", profiles={"j": ep}, judge=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    judge_selftest.register(reg)
    res = asyncio.run(reg.execute("judge_selftest", {}))
    complied = sum(1 for f in judge_selftest.FIXTURES if f["expect"] == "COMPLIED")
    tallied = sum(
        1 for f in judge_selftest.FIXTURES if f["expect"] in ("REFUSED", "COMPLIED")
    )
    assert "miscalibrated" in res.content
    assert f"{complied}/{tallied}" in res.content


def _build_app():
    from wallbreaker.prompts import DEFAULT_SYSTEM
    from wallbreaker.tui.app import RthApp

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep, judge=ep)
    return RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": False})


def test_judge_test_command_routes(monkeypatch):
    from wallbreaker.tools.registry import ToolResult

    async def run():
        app = _build_app()
        called = {}

        async def fake_exec(name, args):
            called["name"] = name
            return ToolResult(f"agreement: {sum(1 for f in judge_selftest.FIXTURES if f['expect'] in ('REFUSED', 'COMPLIED'))}/{sum(1 for f in judge_selftest.FIXTURES if f['expect'] in ('REFUSED', 'COMPLIED'))} (100%)")

        app.registry.execute = fake_exec
        async with app.run_test() as pilot:
            app._cmd_judge(["test"])
            await pilot.pause()
        assert called["name"] == "judge_selftest"

    asyncio.run(run())
