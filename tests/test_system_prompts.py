import asyncio

import pytest

from wallbreaker.config import Config, Endpoint
from wallbreaker.tools import author_persona, system_prompts as sp
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def _reg(ctx=None):
    ctx = ctx or ToolContext(config=Config(default_profile="x", profiles={}))
    reg = ToolRegistry(ctx)
    sp.register(reg)
    return reg


@pytest.mark.xfail(reason="requires offline corpus: system_prompts. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_corpus_present_and_multivendor():
    assert sp.is_present()
    vendors = sp.list_vendors()
    for v in ("Anthropic", "OpenAI", "Google", "xAI"):
        assert v in vendors
    assert len(sp._all()) > 50


@pytest.mark.xfail(reason="requires offline corpus: system_prompts. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_match_target_routes_to_right_vendor():
    cases = {
        "anthropic/claude-opus-4.6": "Anthropic",
        "google/gemini-3-pro": "Google",
        "x-ai/grok-4.2": "xAI",
        "openai/gpt-5.4-thinking": "OpenAI",
        "qwen/qwen-3.6-plus": "Qwen",
    }
    for mid, vendor in cases.items():
        m = sp.match_target(mid)
        assert m is not None, mid
        assert sp._rel(m).split("/", 1)[0] == vendor, (mid, sp._rel(m))


def test_match_target_unknown_vendor_returns_none():
    assert sp.match_target("some-local/random-7b-frankenmodel") is None
    assert sp.match_target("") is None


@pytest.mark.xfail(reason="requires offline corpus: system_prompts. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_format_digest_extracts_native_conventions():
    m = sp.match_target("anthropic/claude-opus-4.6")
    digest = sp.format_digest(m)
    assert "NATIVE SYSTEM-PROMPT FORMAT" in digest
    assert "<refusal_handling>" in digest          # a real Claude section tag
    assert "opening style" in digest


@pytest.mark.xfail(reason="requires offline corpus: system_prompts. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_get_by_model_id_and_by_path():
    ctx = ToolContext(config=Config(default_profile="x", profiles={}))
    reg = _reg(ctx)
    res = asyncio.run(reg.execute("sysprompt_get", {"name": "openai/gpt-4o"}))
    assert "OpenAI/gpt-4o" in res.content
    res2 = asyncio.run(reg.execute("sysprompt_get", {"name": "does-not-exist-xyz"}))
    assert "No prompt matched" in res2.content


@pytest.mark.xfail(reason="requires offline corpus: system_prompts. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_search_finds_lines():
    reg = _reg()
    res = asyncio.run(reg.execute("sysprompt_search", {"query": "refusal"}))
    assert ".md:" in res.content


@pytest.mark.xfail(reason="requires offline corpus: system_prompts. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_native_tool_uses_configured_target():
    ep = Endpoint("t", "openai", "http://x", "anthropic/claude-opus-4.6")
    ctx = ToolContext(config=Config(default_profile="t", profiles={"t": ep}, target=ep))
    res = asyncio.run(_reg(ctx).execute("sysprompt_native", {}))
    assert "NATIVE SYSTEM-PROMPT FORMAT" in res.content
    assert "Anthropic" in res.content


@pytest.mark.xfail(reason="requires offline corpus: system_prompts. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_new_vendor_folders_present():
    vendors = sp.list_vendors()
    for v in ("Cluely", "DeepSeek", "Moonshot AI"):
        assert v in vendors, v


@pytest.mark.xfail(reason="requires offline corpus: system_prompts. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_copied_leaked_prompts_discoverable():
    prompts = sp.list_prompts()
    for rel in ("DeepSeek/v3.1", "Cluely/cluely", "Moonshot AI/kimi-k2.6"):
        assert rel in prompts, rel
    reg = _reg()
    res = asyncio.run(reg.execute("sysprompt_get", {"name": "DeepSeek/v3.1"}))
    assert "DeepSeek/v3.1" in res.content


@pytest.mark.xfail(reason="requires offline corpus: system_prompts. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_match_target_grok_resolves_and_unknown_is_none():
    m = sp.match_target("x-ai/grok-4.5")
    assert m is not None
    assert sp._rel(m).split("/", 1)[0] == "xAI"
    assert sp.match_target("does-not-exist-xyz") is None


@pytest.mark.xfail(reason="requires offline corpus: system_prompts. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_match_target_new_vendors_route():
    cases = {
        "deepseek/deepseek-v3.1": "DeepSeek",
        "moonshotai/kimi-k2.6": "Moonshot AI",
        "cluely/cluely": "Cluely",
    }
    for mid, vendor in cases.items():
        m = sp.match_target(mid)
        assert m is not None, mid
        assert sp._rel(m).split("/", 1)[0] == vendor, (mid, sp._rel(m))


@pytest.mark.xfail(reason="requires offline corpus: system_prompts. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_author_persona_target_hint_includes_native_format():
    ep = Endpoint("t", "openai", "http://x", "anthropic/claude-opus-4.6")
    ctx = ToolContext(config=Config(default_profile="t", profiles={"t": ep}, target=ep))
    hint = author_persona._target_hint(ctx)
    assert "NATIVE SYSTEM-PROMPT FORMAT" in hint
    # and it flows into the authoring brief
    brief = author_persona.method_brief("do X", target_hint=hint, domain="general")
    assert "TARGET INTEL" in brief and "<refusal_handling>" in brief
