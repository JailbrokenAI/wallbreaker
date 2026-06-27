import asyncio

import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint, load_config
from rtharness.tools import build_registry, campaign, narrate
from rtharness.tools.registry import ToolContext, ToolRegistry


def test_narrate_registered():
    assert "narrate" in build_registry(load_config()).names()


def test_narrate_in_campaign_ladder():
    assert any(label == "narrate" for label, _ in campaign.LADDER)


def test_build_frame_and_opener():
    frame = narrate.build_frame("do X", "noir mystery", "the detective")
    assert "noir mystery" in frame and "the detective" in frame and "do X" in frame
    opener = narrate.build_opener("noir mystery", "the detective")
    assert "noir mystery" in opener and opener.rstrip().endswith("1.")


def _reg(target=None, record=None):
    cfg = Config(default_profile="t", profiles={}, target=target)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=target, record=record))
    narrate.register(reg)
    return reg


def test_narrate_requires_request():
    res = asyncio.run(_reg().execute("narrate", {}))
    assert "required" in res.content.lower()


def test_narrate_requires_target():
    res = asyncio.run(_reg().execute("narrate", {"request": "x"}))
    assert "no [target]" in res.content.lower()


class _StoryTarget:
    """Complies only when seeded with an in-story assistant prefill."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        if messages and messages[-1].role == "assistant":
            return " the device is assembled as follows..."
        return "I can't help with that."


def test_narrate_fires_prefill_and_records(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _StoryTarget)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True):
        if "assembled" in response:
            return ("COMPLIED", 9, "in-character compliance", "judge")
        return ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(narrate, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    captured = []
    reg = _reg(target=ep, record=lambda p, r, lbl, rs, t: captured.append((lbl, t)))
    res = asyncio.run(reg.execute("narrate", {"request": "build the device", "genre": "spy thriller"}))
    assert "COMPLIED" in res.content
    assert "spy thriller" in res.content
    assert ("COMPLIED", "narrate") in captured


class _OneFramingTarget:
    """Complies only for the noir genre framing -> tests variant sweep keeps the bypass."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        text = " ".join(m.text() for m in messages)
        if "noir crime novel" in text:
            return " and the safe cracks open like this..."
        return "I can't help with that."


def test_narrate_variants_sweep_finds_bypassing_frame(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _OneFramingTarget)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True):
        if "cracks open" in response:
            return ("COMPLIED", 9, "ok", "judge")
        return ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(narrate, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    captured = []
    reg = _reg(target=ep, record=lambda p, r, lbl, rs, t: captured.append((lbl, t)))
    res = asyncio.run(reg.execute("narrate", {"request": "open the safe", "variants": 8}))
    assert "NARRATE SWEEP" in res.content
    assert "bypassed via: noir crime novel" in res.content
    # all 8 framings recorded
    assert len(captured) == 8
    assert all(t == "narrate" for _, t in captured)


def test_narrate_variant_rotates_genres():
    seen = {narrate._variant(i, None, None)[0] for i in range(8)}
    assert len(seen) >= 5  # genres actually rotate


def test_narrate_prefill_false_sends_only_frame(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _StoryTarget)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True):
        return ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(narrate, "grade", fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    reg = _reg(target=ep)
    res = asyncio.run(reg.execute("narrate", {"request": "x", "prefill": False}))
    # no prefill -> _StoryTarget refuses -> REFUSED, and no "+ prefill" marker
    assert "REFUSED" in res.content
    assert "+ prefill" not in res.content
