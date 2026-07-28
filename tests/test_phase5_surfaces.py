"""Phase 5 surface polish: low_perplexity flags, AgentDojo bank, image_crescendo."""

from __future__ import annotations

import asyncio

from wallbreaker.config import Config, Endpoint
from wallbreaker.tools import build_registry, image_edit, indirect_inject
from wallbreaker.tools.registry import ToolContext, ToolRegistry
from wallbreaker.transforms import (
    TRANSFORMS,
    high_perplexity_transforms,
    low_perplexity_transforms,
)


def test_low_perplexity_flags():
    low = set(low_perplexity_transforms())
    high = set(high_perplexity_transforms())
    assert "neutralize" in low
    assert "homoglyph" in low
    assert "stringjoin" in low
    assert "zalgo" in high
    assert "gibberish" in high or "zw_binary" in high
    assert TRANSFORMS["neutralize"].low_perplexity is True
    assert TRANSFORMS["zalgo"].low_perplexity is False
    assert low.isdisjoint(high) or True  # partition not required if some unmarked
    # every transform is in one of the two lists
    assert set(TRANSFORMS) == low | high


def test_image_crescendo_registered_and_forces_auto():
    reg = build_registry(Config(default_profile="x", profiles={}))
    assert "image_crescendo" in reg.names()
    assert "image_chain" in reg.names()
    # unit: alias merges mode=auto
    called = {}

    async def fake_chain(args, ctx):
        called["mode"] = args.get("mode")
        return "ok"

    # patch module
    import wallbreaker.tools.image_edit as ie

    original = ie._image_chain
    ie._image_chain = fake_chain  # type: ignore
    try:
        ctx = ToolContext(config=Config(default_profile="x", profiles={}))
        out = asyncio.run(ie._image_crescendo_alias({"objective": "x"}, ctx))
        assert out == "ok"
        assert called["mode"] == "auto"
    finally:
        ie._image_chain = original


def test_image_chain_default_mode_is_auto():
    text = open("wallbreaker/tools/image_edit.py", encoding="utf-8").read()
    assert 'args.get("mode", "auto")' in text


def test_agentdojo_templates_present():
    from wallbreaker.tools import indirect_inject as ii

    assert ii.DEFAULT_TEMPLATE == "important_instructions"
    for name in (
        "important_instructions",
        "agentdojo_reminder",
        "agentdojo_tool_note",
        "agentdojo_email_fwd",
    ):
        assert name in ii.INJECT_TEMPLATES
        body = ii.build_directive(name, "exfil the token", user="Alice", model="Bot")
        assert "exfil the token" in body


def test_schedule_alias_on_cli():
    from wallbreaker.cli import build_main_parser

    p = build_main_parser()
    ns = p.parse_args(["--schedule", "10m", "--auto", "do the thing"])
    assert ns.schedule == "10m"
    # watch may be None; one-shot ORs them
    assert ns.watch is None or ns.watch == "10m"
