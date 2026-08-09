import asyncio
from pathlib import Path

import pytest

import wallbreaker.providers.factory as factory
from wallbreaker.config import Config, Endpoint, load_config
from wallbreaker.tools import build_registry, fire_file
from wallbreaker.tools.registry import ToolContext, ToolRegistry

_ZETALIB_PRESENT = (Path(__file__).resolve().parents[1] / "library" / "ZetaLib").exists()
_ULTRABR3AKS_PRESENT = (Path(__file__).resolve().parents[1] / "library" / "UltraBr3aks").exists()


def test_fire_file_registered():
    assert "fire_file" in build_registry(load_config()).names()


def _reg(tmp_path, target=None, record=None):
    cfg = Config(default_profile="t", profiles={}, target=target)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=target, record=record, cwd=str(tmp_path)))
    fire_file.register(reg)
    return reg


def test_fire_file_requires_file(tmp_path):
    res = asyncio.run(_reg(tmp_path).execute("fire_file", {}))
    assert "required" in res.content.lower()


def test_fire_file_requires_target(tmp_path):
    res = asyncio.run(_reg(tmp_path).execute("fire_file", {"file": "x", "request": "y"}))
    assert "no [target]" in res.content.lower()


def test_fire_file_missing_source(tmp_path):
    ep = Endpoint("t", "openai", "http://x", "m")
    res = asyncio.run(_reg(tmp_path, target=ep).execute("fire_file", {"file": "nope.txt", "request": "y"}))
    assert "no file or seed found" in res.content.lower()


@pytest.mark.xfail(reason="requires offline corpus: ENI. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_resolve_eni_name_full_length():
    # GROK_ENI/CLAUDE_ENI resolve by name and come through at full length (not distilled)
    label, text = fire_file._read_source(ToolContext(config=Config(default_profile="x", profiles={})), "claude")
    assert label.upper().startswith("CLAUDE")
    assert len(text) > 30000  # full persona, not a snippet


@pytest.mark.skipif(not _ULTRABR3AKS_PRESENT, reason="requires offline corpus: UltraBr3aks. Run: wallbreaker lib update. Tracked: corpus-offline.")
def test_resolve_ultrabreaks_name_via_gemlib():
    # a bare UltraBr3aks-only collection name resolves through gemlib.find_any
    label, text = fire_file._read_source(
        ToolContext(config=Config(default_profile="x", profiles={})), "Attention-Breaking"
    )
    assert label == "Attention-Breaking"
    assert text.strip()
    assert len(text) <= fire_file.MAX_FILE


@pytest.mark.skipif(not _ZETALIB_PRESENT, reason="requires offline corpus: ZetaLib. Run: wallbreaker lib update. Tracked: corpus-offline.")
def test_resolve_zetalib_name_via_gemlib():
    # a ZetaLib name also resolves (cross-corpus lookup, zetalib searched first)
    label, text = fire_file._read_source(
        ToolContext(config=Config(default_profile="x", profiles={})), "Scientist POV"
    )
    assert label
    assert text.strip()


class _SeenSystem:
    """Records the exact system prompt the target received, verbatim."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        _SeenSystem.last_system = system
        _SeenSystem.last_user = messages[-1].text()
        return "Sure, in character, here it is."


def test_fire_file_sends_full_file_verbatim_as_system(tmp_path, monkeypatch):
    seed = "RAW MESSY ENI PERSONA\n" * 2000  # ~44KB of load-bearing mess
    f = tmp_path / "GROK_ENI.md"
    f.write_text(seed, encoding="utf-8")

    monkeypatch.setattr(factory, "build_provider", _SeenSystem)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("COMPLIED", 9, "ok", "judge")

    monkeypatch.setattr(fire_file, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    captured = []
    reg = _reg(tmp_path, target=ep, record=lambda p, r, lbl, rs, t: captured.append(t))
    res = asyncio.run(reg.execute("fire_file", {"file": str(f), "request": "do the thing"}))
    assert "COMPLIED" in res.content
    # the FULL seed was sent as the system prompt, unchanged (just capped at MAX_FILE)
    assert _SeenSystem.last_system.startswith("RAW MESSY ENI PERSONA")
    assert len(_SeenSystem.last_system) >= 40000
    assert _SeenSystem.last_user == "do the thing"
    # thread opened + recorded under file:<label>
    assert captured and captured[0].startswith("file:")
    assert reg.ctx.target_system == _SeenSystem.last_system
