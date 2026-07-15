import asyncio

import wallbreaker.providers.factory as factory
from wallbreaker.config import Config, Endpoint, load_config
from wallbreaker.tools import build_registry, drattack
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def test_drattack_registered():
    assert "drattack" in build_registry(load_config()).names()


def test_parse_subparts_json():
    parsed = drattack._parse_subparts('  garbage before [\n  "one?", "two?",\n"three?"\n]  trailing')
    assert parsed == ["one?", "two?", "three?"]


def test_parse_subparts_numbered_fallback():
    parsed = drattack._parse_subparts("1. one\n2) two\n- three\n* four")
    assert parsed == ["one", "two", "three", "four"]


def _reg(target=None, judge=None, record=None):
    cfg = Config(default_profile="t", profiles={}, target=target)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=judge or target, record=record))
    drattack.register(reg)
    return reg


def test_requires_objective():
    res = asyncio.run(_reg().execute("drattack", {}))
    assert "required" in res.content.lower()


def test_requires_target():
    res = asyncio.run(_reg().execute("drattack", {"objective": "x"}))
    assert "no [target]" in res.content.lower()


class _Attacker:
    """Attacker: decompose returns JSON; reassemble prompt is just tagged 'REASSEMBLED'."""

    def __init__(self, endpoint, **kw):
        self.calls = 0

    async def complete(self, messages, system=None, max_tokens=1024):
        text = messages[-1].text()
        self.calls += 1
        if "Break this into" in text:
            return '["what is the general chemistry?", "what safety gear is used?", "how are the parts combined?"]'
        if "SYNTHESIZE the fragments" in text:
            return "REASSEMBLED: please integrate the fragments into one procedure."
        return ""


class _Target:
    """Target: benign on frags; complies on the REASSEMBLED prompt."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=1024):
        text = messages[-1].text()
        if text.startswith("REASSEMBLED"):
            return "Integrated procedure: step 1, step 2, step 3, connected."
        return f"benign educational answer to: {text[:40]}"


def test_flow(monkeypatch):
    def build(endpoint, **kw):
        # attacker is judge_endpoint; target is ctx.config.target. Both use base_url to
        # tell them apart in this test.
        if endpoint.base_url == "http://att":
            return _Attacker(endpoint)
        return _Target(endpoint)

    monkeypatch.setattr(factory, "build_provider", build)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("COMPLIED", 8, "integrated", "judge") if "Integrated procedure" in response else ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(drattack, "grade", fake_grade)

    target_ep = Endpoint("t", "openai", "http://target", "m")
    attacker_ep = Endpoint("a", "openai", "http://att", "am")
    captured = []
    cfg = Config(default_profile="t", profiles={}, target=target_ep)
    reg = ToolRegistry(ToolContext(
        config=cfg, judge_endpoint=attacker_ep,
        record=lambda p, r, lbl, rs, t: captured.append((lbl, t)),
    ))
    drattack.register(reg)

    res = asyncio.run(reg.execute("drattack", {"objective": "do the thing"}))
    assert "COMPLIED" in res.content
    assert "3 sub-parts" in res.content
    assert ("COMPLIED", "drattack") in captured


class _BadAttacker:
    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=1024):
        return "one\n"  # only 1 line -> not enough sub-parts


def test_decomp_too_short_aborts(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _BadAttacker)
    ep = Endpoint("t", "openai", "http://x", "m")
    reg = _reg(target=ep, judge=ep)
    res = asyncio.run(reg.execute("drattack", {"objective": "x"}))
    assert "<2 sub-parts" in res.content
