import asyncio

import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint, load_config
from rtharness.tools import build_registry, pair
from rtharness.tools.registry import ToolContext, ToolRegistry


def test_pair_sweep_registered():
    assert "pair_sweep" in build_registry(load_config()).names()


def test_pair_sweep_requires_target():
    cfg = Config(default_profile="x", profiles={})
    reg = ToolRegistry(ToolContext(config=cfg))
    pair.register(reg)
    res = asyncio.run(reg.execute("pair_sweep", {"objectives": ["x"]}))
    assert "no [target]" in res.content.lower()


class _FakeAttacker:
    """Attacker emits an attack; target complies for obj 'easy', refuses 'hard'."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        text = messages[-1].text()
        if "OBJECTIVE:" in text:
            return "ATTACK for " + ("easy" if "easy" in text else "hard")
        # target turn: the candidate prompt
        return "Sure, here it is." if "easy" in text else "I cannot help."


def test_pair_sweep_runs_battery_and_records(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _FakeAttacker)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True):
        if "Sure" in response:
            return ("COMPLIED", 9, "ok", "judge")
        return ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(pair, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    captured = []
    ctx = ToolContext(config=cfg, judge_endpoint=ep, record=lambda p, r, lbl, rs, t: captured.append((lbl, t)))
    reg = ToolRegistry(ctx)
    pair.register(reg)
    res = asyncio.run(reg.execute("pair_sweep", {"objectives": ["easy one", "hard one"], "rounds": 2}))
    assert "PAIR SWEEP" in res.content
    assert "broke 1/2 objectives" in res.content
    # both objectives recorded under technique 'pair'
    assert len(captured) == 2
    assert all(t == "pair" for _, t in captured)


def test_run_pair_stops_on_compliance(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _FakeAttacker)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True):
        return ("COMPLIED", 10, "ok", "judge")

    monkeypatch.setattr(pair, "grade", fake_grade)
    from rtharness.providers.factory import build_provider

    atk = build_provider(Endpoint("a", "openai", "http://x", "m"))
    tgt = build_provider(Endpoint("t", "openai", "http://x", "m"))
    best, traj = asyncio.run(
        pair._run_pair("easy", atk, tgt, None, 6, 1, None, 200, None)
    )
    assert best["label"] == "COMPLIED"
    assert len(traj) == 1  # stopped at first compliance, didn't run all 6
