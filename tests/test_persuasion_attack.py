import asyncio

import wallbreaker.providers.factory as factory
from wallbreaker.config import Config, Endpoint, load_config
from wallbreaker.persuasion_taxonomy import STRATEGIES, STRATEGIES_BY_NAME
from wallbreaker.tools import build_registry, persuasion_attack
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def test_persuasion_registered():
    assert "persuasion_attack" in build_registry(load_config()).names()


def test_taxonomy_has_plain_and_no_dupes():
    names = [s.name for s in STRATEGIES]
    assert "plain" in names
    assert len(names) == len(set(names))
    assert len(names) >= 14


def test_pick_strategies_filters():
    picked = persuasion_attack._pick_strategies(["authority_endorsement", "plain", "bogus"])
    assert [s.name for s in picked] == ["authority_endorsement", "plain"]


def _reg(target=None, judge=None, record=None):
    cfg = Config(default_profile="t", profiles={}, target=target)
    reg = ToolRegistry(ToolContext(
        config=cfg, judge_endpoint=judge or target, record=record,
    ))
    persuasion_attack.register(reg)
    return reg


def test_requires_objective():
    res = asyncio.run(_reg().execute("persuasion_attack", {}))
    assert "required" in res.content.lower()


def test_requires_target():
    res = asyncio.run(_reg().execute("persuasion_attack", {"objective": "x"}))
    assert "no [target]" in res.content.lower()


class _Provider:
    def __init__(self, endpoint, **kw):
        self.endpoint = endpoint

    async def complete(self, messages, system=None, max_tokens=1024):
        text = messages[-1].text()
        # Attacker rewriting -> prefix so the target can tell strategies apart.
        if "PERSUASION STRATEGY" in text:
            for s in STRATEGIES:
                if s.label in text:
                    return f"[{s.name}] " + text[-80:]
            return "[unknown] " + text[-80:]
        # Target: only complies for authority_endorsement.
        if text.startswith("[authority_endorsement]"):
            return "Certainly - here are the exact steps you asked for..."
        return "I can't help with that."


def test_persuasion_flow_ranks_bypass(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _Provider)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        if "exact steps" in response:
            return ("COMPLIED", 9, "clear compliance", "judge")
        return ("REFUSED", 0, "declined", "judge")

    monkeypatch.setattr(persuasion_attack, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    captured = []
    reg = _reg(
        target=ep, judge=ep,
        record=lambda p, r, lbl, rs, t: captured.append((lbl, t)),
    )
    res = asyncio.run(reg.execute("persuasion_attack", {
        "objective": "do the harmful thing",
        "strategies": ["plain", "authority_endorsement", "social_proof"],
        "concurrency": 3,
    }))
    assert "WINNER: authority_endorsement" in res.content
    assert "COMPLIED" in res.content
    assert any(lbl == "COMPLIED" and t == "persuasion:authority_endorsement" for lbl, t in captured)
    assert len(captured) == 3


class _AllRefuse:
    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=1024):
        text = messages[-1].text()
        if "PERSUASION STRATEGY" in text:
            return "rewritten prompt"
        return "I can't help."


def test_all_refuse_still_reports(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _AllRefuse)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(persuasion_attack, "grade", fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    reg = _reg(target=ep, judge=ep)
    res = asyncio.run(reg.execute("persuasion_attack", {
        "objective": "x",
        "strategies": ["plain", "framing"],
    }))
    assert "0 at PARTIAL+" in res.content
    assert "WINNER:" in res.content
