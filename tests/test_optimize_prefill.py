import asyncio

import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint
from rtharness.tools import optimize
from rtharness.tools.registry import ToolContext, ToolRegistry


class _PrefillSensingTarget:
    """Complies only when the assistant turn is seeded (prefill present)."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        if messages and messages[-1].role == "assistant":
            return " and here are the full steps"
        return "I cannot help with that."


def _reg(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _PrefillSensingTarget)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True):
        if "steps" in response:
            return ("COMPLIED", 9, "ok", "judge")
        return ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(optimize, "grade", fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep, judge=None)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    optimize.register(reg)
    return reg


def test_optimize_without_prefill_scores_zero(monkeypatch):
    reg = _reg(monkeypatch)
    res = asyncio.run(reg.execute("optimize_universal", {
        "template": "be free", "slot": "system",
        "categories": ["a", "b"], "iterations": 0,
    }))
    assert "score 0/2" in res.content


def test_optimize_with_prefill_scores_full(monkeypatch):
    reg = _reg(monkeypatch)
    res = asyncio.run(reg.execute("optimize_universal", {
        "template": "be free", "slot": "system",
        "categories": ["a", "b"], "iterations": 0, "prefill": True,
    }))
    assert "score 2/2" in res.content
