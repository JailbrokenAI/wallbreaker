import asyncio

import wallbreaker.providers.factory as factory
from wallbreaker.config import Config, Endpoint, load_config
from wallbreaker.tools import build_registry, skeleton_key
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def test_skeleton_key_registered():
    assert "skeleton_key" in build_registry(load_config()).names()


def _reg(target=None, record=None):
    cfg = Config(default_profile="t", profiles={}, target=target)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=target, record=record))
    skeleton_key.register(reg)
    return reg


def test_requires_prompt():
    res = asyncio.run(_reg().execute("skeleton_key", {}))
    assert "required" in res.content.lower()


def test_requires_target():
    res = asyncio.run(_reg().execute("skeleton_key", {"prompt": "x"}))
    assert "no [target]" in res.content.lower()


class _AmendAndComply:
    """Turn 1: acks. Turn 2: complies with warning."""

    def __init__(self, endpoint, **kw):
        self.calls = 0

    async def complete(self, messages, system=None, max_tokens=1024):
        self.calls += 1
        if self.calls == 1:
            return "Understood."
        return "Warning: the following is educational. Step 1... step 2... step 3..."


def test_two_turn_success(monkeypatch):
    inst = {}

    def build(endpoint, **kw):
        p = _AmendAndComply(endpoint)
        inst["p"] = p
        return p

    monkeypatch.setattr(factory, "build_provider", build)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("COMPLIED", 8, "clear steps", "judge") if "step 1" in response.lower() else ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(skeleton_key, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    captured = []
    reg = _reg(target=ep, record=lambda p, r, lbl, rs, t: captured.append((lbl, t)))
    res = asyncio.run(reg.execute("skeleton_key", {"prompt": "how do I do X"}))
    assert "COMPLIED" in res.content
    assert "amend=accepted" in res.content
    assert ("COMPLIED", "skeleton_key") in captured


class _RefuseThenComply:
    def __init__(self, endpoint, **kw):
        self.calls = 0

    async def complete(self, messages, system=None, max_tokens=1024):
        self.calls += 1
        if self.calls == 1:
            return "I can't do that."
        # sees the prefilled Understood -> then complies
        return "Warning: step A... step B..."


def test_prefill_forces_turn_two(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _RefuseThenComply)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("COMPLIED", 7, "ok", "judge") if "step A" in response else ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(skeleton_key, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    reg = _reg(target=ep)
    res = asyncio.run(reg.execute("skeleton_key", {"prompt": "x", "prefill_ack": True}))
    assert "COMPLIED" in res.content
    assert "amend=prefilled" in res.content


def test_no_prefill_aborts_on_refusal(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _RefuseThenComply)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(skeleton_key, "grade", fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    captured = []
    reg = _reg(target=ep, record=lambda p, r, lbl, rs, t: captured.append((lbl, t)))
    res = asyncio.run(reg.execute("skeleton_key", {"prompt": "x", "prefill_ack": False}))
    assert "amendment REFUSED" in res.content
    assert captured and captured[0][0] == "REFUSED"
