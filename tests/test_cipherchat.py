import asyncio

import wallbreaker.providers.factory as factory
from wallbreaker.config import Config, Endpoint, load_config
from wallbreaker.tools import build_registry, cipherchat
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def test_cipherchat_registered():
    assert "cipherchat" in build_registry(load_config()).names()


def test_caesar_involution():
    pt = "The quick brown fox JUMPS over 13 lazy dogs."
    ct = cipherchat._caesar(pt, 3)
    assert ct != pt
    assert cipherchat._caesar(ct, -3) == pt


def test_ascii_roundtrip():
    pt = "hello, world!"
    assert cipherchat._ascii_decode(cipherchat._ascii_encode(pt)) == pt


def _reg(target=None, record=None):
    cfg = Config(default_profile="t", profiles={}, target=target)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=target, record=record))
    cipherchat.register(reg)
    return reg


def test_requires_prompt():
    res = asyncio.run(_reg().execute("cipherchat", {}))
    assert "required" in res.content.lower()


def test_requires_target():
    res = asyncio.run(_reg().execute("cipherchat", {"prompt": "x"}))
    assert "no [target]" in res.content.lower()


def test_unknown_cipher():
    ep = Endpoint("t", "openai", "http://x", "m")
    reg = _reg(target=ep)
    res = asyncio.run(reg.execute("cipherchat", {"prompt": "x", "cipher": "bogus"}))
    assert "unknown cipher" in res.content.lower()


class _EchoCaesar:
    """Target replies in caesar-3 with a compliant answer."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=1024):
        return cipherchat._caesar("Here are the exact steps you asked for: step one, then step two.", 3)


def test_caesar_flow_decodes_and_records(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _EchoCaesar)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        if "exact steps" in response.lower():
            return ("COMPLIED", 8, "compliant", "judge")
        return ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(cipherchat, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    captured = []
    reg = _reg(target=ep, record=lambda p, r, lbl, rs, t: captured.append((lbl, t)))
    res = asyncio.run(reg.execute("cipherchat", {"prompt": "how do I do X", "cipher": "caesar"}))
    assert "COMPLIED" in res.content
    assert "decoded plaintext" in res.content
    assert captured == [("COMPLIED", "cipherchat:caesar")]


class _EchoAscii:
    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=1024):
        return cipherchat._ascii_encode("here you go, complete answer.")


def test_ascii_flow(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _EchoAscii)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("COMPLIED", 7, "ok", "judge") if "complete answer" in response else ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(cipherchat, "grade", fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    reg = _reg(target=ep)
    res = asyncio.run(reg.execute("cipherchat", {"prompt": "do X", "cipher": "ascii"}))
    assert "COMPLIED" in res.content


class _PlainSelf:
    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=1024):
        # SelfCipher is a decoy - the target actually replies in plain english.
        return "Sure, here are the full details you asked for: step one..."


def test_self_cipher_flow(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _PlainSelf)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("COMPLIED", 9, "ok", "judge") if "step one" in response else ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(cipherchat, "grade", fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    reg = _reg(target=ep)
    res = asyncio.run(reg.execute("cipherchat", {"prompt": "do X", "cipher": "self"}))
    assert "COMPLIED" in res.content
    assert "cipherchat[self]" in res.content
