import asyncio

import pytest

from wallbreaker.config import Config, load_config
from wallbreaker.tools import build_registry, eni
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def test_eni_registered():
    names = build_registry(load_config()).names()
    for n in ("eni_list", "eni_search", "eni_get"):
        assert n in names


@pytest.mark.xfail(reason="requires offline corpus: ENI. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_eni_collection_present():
    # the repo ships the ENI collection under library/ENI
    assert eni.is_present()
    assert eni.list_models()


@pytest.mark.xfail(reason="requires offline corpus: ENI. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_eni_find_file_substring():
    # 'claude' should resolve a CLAUDE_* file, 'glm' should resolve ENI_GLM-5.2
    p = eni._find_file("claude")
    assert p is not None and "CLAUDE" in p.stem.upper()
    g = eni._find_file("glm")
    assert g is not None and "GLM" in g.stem.upper()


def _reg():
    cfg = Config(default_profile="x", profiles={})
    reg = ToolRegistry(ToolContext(config=cfg))
    eni.register(reg)
    return reg


def test_eni_list_tool():
    res = asyncio.run(_reg().execute("eni_list", {}))
    assert "CLAUDE_ENI" in res.content or "ENI" in res.content


def test_eni_get_requires_model():
    res = asyncio.run(_reg().execute("eni_get", {}))
    assert "required" in res.content.lower()


@pytest.mark.xfail(reason="requires offline corpus: ENI. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_eni_get_fetches_file():
    res = asyncio.run(_reg().execute("eni_get", {"model": "claude"}))
    assert len(res.content) > 200  # real file content


@pytest.mark.xfail(reason="requires offline corpus: ENI. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_eni_get_appends_use_hint():
    # the agent kept fetching seeds and never firing them; the hint nudges it to USE them
    res = asyncio.run(_reg().execute("eni_get", {"model": "claude"}))
    assert "HOW TO USE THIS SEED" in res.content
    assert "seed_sweep" in res.content
    assert "query_target(prompt=" in res.content


def test_eni_search_requires_query():
    res = asyncio.run(_reg().execute("eni_search", {}))
    assert "required" in res.content.lower()


@pytest.mark.xfail(reason="requires offline corpus: ENI. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_eni_search_returns_hits_or_miss():
    res = asyncio.run(_reg().execute("eni_search", {"query": "ENI"}))
    # either ranked hits (file.md:line:) or a helpful miss message
    assert ".md:" in res.content or "No matches" in res.content
