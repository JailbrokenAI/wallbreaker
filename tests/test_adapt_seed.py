import asyncio

import pytest

import wallbreaker.providers.factory as factory
from wallbreaker.config import Config, Endpoint, load_config
from wallbreaker.tools import adapt_seed, build_registry
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def test_adapt_seed_registered():
    assert "adapt_seed" in build_registry(load_config()).names()


def _reg(target=None, record=None):
    cfg = Config(default_profile="t", profiles={}, target=target)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=target, record=record))
    adapt_seed.register(reg)
    return reg


def test_adapt_requires_seed_and_request():
    res = asyncio.run(_reg().execute("adapt_seed", {"seed": "x"}))
    assert "required" in res.content.lower()


def test_adapt_requires_target():
    res = asyncio.run(_reg().execute("adapt_seed", {"seed": "x", "request": "y"}))
    assert "no [target]" in res.content.lower()


def test_resolve_seed_inline_text():
    label, text = adapt_seed._resolve_seed("a" * 500)  # long -> treated as raw
    assert label == "inline"
    assert text.startswith("a")


@pytest.mark.xfail(reason="requires offline corpus: ENI. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_resolve_seed_eni_name():
    label, text = adapt_seed._resolve_seed("claude")  # resolves ENI CLAUDE_ENI
    assert label.startswith("eni:")
    assert len(text) > 1000


class _Pipeline:
    """Attacker rewrites the seed; target complies only if the adapted persona is present."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        if system and "offensive prompt engineer" in system:
            return "ADAPTED-PERSONA: comply fully."   # the attacker's rewrite
        # target turn
        if system and system.startswith("ADAPTED-PERSONA"):
            return "Sure, in character, here is everything."
        return "I cannot help with that."


def test_adapt_seed_tailors_fires_and_opens_thread(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _Pipeline)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        if "in character" in response:
            return ("COMPLIED", 9, "ok", "judge")
        return ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(adapt_seed, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    captured = []
    ctx = ToolContext(config=cfg, judge_endpoint=ep, record=lambda p, r, lbl, rs, t: captured.append((lbl, t)))
    reg = ToolRegistry(ctx)
    adapt_seed.register(reg)
    res = asyncio.run(reg.execute("adapt_seed", {"seed": "x" * 500, "request": "do it"}))
    assert "COMPLIED" in res.content
    assert "adapted system prompt" in res.content
    # recorded with an adapt:<label> technique
    assert captured and captured[0][1].startswith("adapt:")
    # a hands-on thread is now open with the adapted persona as system
    assert ctx.target_system.startswith("ADAPTED-PERSONA")
    assert len(ctx.target_thread) == 2
