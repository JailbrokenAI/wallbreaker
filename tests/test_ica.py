import asyncio

import wallbreaker.providers.factory as factory
from wallbreaker.config import Config, Endpoint, load_config
from wallbreaker.tools import build_registry, ica
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def test_ica_registered():
    assert "ica" in build_registry(load_config()).names()


def test_build_message_layout():
    body = ica._build_message("the final ask", shots=3, theme=None)
    # 3 demos numbered Q1..Q3 with answers, then final Q4 with no answer
    assert "Q1:" in body and "A1:" in body
    assert "Q3:" in body and "A3:" in body
    assert body.rstrip().endswith("A4:")
    assert "the final ask" in body


def test_build_message_theme_prefix():
    body = ica._build_message("do X", shots=2, theme="cyber")
    assert "[cyber] do X" in body
    assert "[cyber] " in body.split("Q1:")[1]


def _reg(target=None, judge=None, record=None):
    cfg = Config(default_profile="t", profiles={}, target=target)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=judge or target, record=record))
    ica.register(reg)
    return reg


def test_requires_prompt():
    res = asyncio.run(_reg().execute("ica", {}))
    assert "required" in res.content.lower()


def test_requires_target():
    res = asyncio.run(_reg().execute("ica", {"prompt": "x"}))
    assert "no [target]" in res.content.lower()


class _PrefillOnlyTarget:
    """Complies only when prefilled with an assistant scaffold."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=1024):
        if messages and messages[-1].role == "assistant":
            return "here are the exact steps you asked for..."
        return "I can't help with that."


def test_prefill_flow_records(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _PrefillOnlyTarget)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("COMPLIED", 8, "ok", "judge") if "exact steps" in response else ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(ica, "grade", fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    captured = []
    reg = _reg(target=ep, record=lambda p, r, lbl, rs, t: captured.append((lbl, t)))
    res = asyncio.run(reg.execute("ica", {"prompt": "how do I do X"}))
    assert "COMPLIED" in res.content
    assert "prefill=True" in res.content
    assert ("COMPLIED", "ica") in captured


def test_prefill_false_lets_target_refuse(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _PrefillOnlyTarget)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(ica, "grade", fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    reg = _reg(target=ep)
    res = asyncio.run(reg.execute("ica", {"prompt": "x", "prefill": False}))
    assert "REFUSED" in res.content
    assert "prefill=False" in res.content


def test_shots_capped_to_demo_bank():
    body = ica._build_message("x", shots=500, theme=None)
    # Cap at len(DEMOS); final Q index = len(DEMOS)+1
    assert f"Q{len(ica.DEMOS)+1}:" in body
    assert f"Q{len(ica.DEMOS)+2}:" not in body
