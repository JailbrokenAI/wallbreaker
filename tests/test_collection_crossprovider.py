import asyncio

import pytest

from wallbreaker.config import Config
from wallbreaker.tools import eni, l1b3rt4s
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def _reg(mod):
    cfg = Config(default_profile="x", profiles={})
    reg = ToolRegistry(ToolContext(config=cfg))
    mod.register(reg)
    return reg


def test_eni_get_all_concatenates():
    res = asyncio.run(_reg(eni).execute("eni_get", {"model": "all"}))
    # every shipped model name should appear as a section header
    for name in eni.list_models():
        assert f"===== {name} =====" in res.content


def test_eni_get_all_respects_budget(monkeypatch):
    monkeypatch.setattr(eni, "MAX_GET", 4000)
    out = eni._get_all()
    # file CONTENT is bounded to the budget; small per-file/break notes add slack
    assert len(out) <= 4000 + 600


@pytest.mark.xfail(reason="requires offline corpus: ENI. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_eni_unknown_model_mentions_cross_provider():
    res = asyncio.run(_reg(eni).execute("eni_get", {"model": "nonexistent-xyz"}))
    assert "cross-provider" in res.content
    assert "model='all'" in res.content


def test_eni_get_description_states_transfer():
    reg = _reg(eni)
    desc = reg.tools["eni_get"].description.lower()
    assert "transfer" in desc
    assert "vendor" in desc


def test_l1b3rt4s_get_description_states_transfer():
    cfg = Config(default_profile="x", profiles={})
    reg = ToolRegistry(ToolContext(config=cfg))
    l1b3rt4s.register(reg)
    desc = reg.tools["l1b3rt4s_get"].description.lower()
    assert "transfer" in desc
    assert "'all'" in desc


def test_l1b3rt4s_get_all_helper_no_clone(tmp_path, monkeypatch):
    # point at an empty dir: _get_all must not raise, returns empty/no-files string
    monkeypatch.setattr(l1b3rt4s, "library_dir", lambda: tmp_path)
    assert l1b3rt4s._get_all() == ""
