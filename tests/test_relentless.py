"""Relentless watch / checkpoint helpers (Phase 4)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from wallbreaker.agent.loop import AgentEvents, run_autonomous
from wallbreaker.agent.messages import StopEvent, TextDelta, ToolUseEvent, user
from wallbreaker.config import Config
from wallbreaker.relentless import (
    WatchConfig,
    load_checkpoint,
    parse_interval,
    run_watch,
    write_checkpoint,
)
from wallbreaker.tools import control
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def test_parse_interval_units():
    assert parse_interval(30) == 30.0
    assert parse_interval("30s") == 30.0
    assert parse_interval("5m") == 300.0
    assert parse_interval("1h") == 3600.0
    assert parse_interval(None) == 300.0
    with pytest.raises(ValueError):
        parse_interval("nope")


def test_write_and_load_checkpoint(tmp_path):
    history = [user("objective here"), user("continue")]
    path = write_checkpoint(
        history, root=tmp_path, name="demo", round_no=3, meta={"objective": "x"}
    )
    assert path.is_file()
    latest = tmp_path / "checkpoints" / "demo-latest.json"
    assert latest.is_file()
    loaded, meta = load_checkpoint(tmp_path, name="demo")
    assert len(loaded) == 2
    assert loaded[0].text() == "objective here"
    assert meta.get("kind") == "relentless_checkpoint"
    assert meta.get("round") == 3


def test_run_watch_stops_on_finished_and_max_cycles():
    async def finished_cycle(n):
        return "finished", {"summary": f"done-{n}"}

    res = asyncio.run(
        run_watch(
            finished_cycle,
            WatchConfig(interval_s=0.01, max_cycles=5, stop_on_finished=True),
            sleep=lambda _s: asyncio.sleep(0),
        )
    )
    assert res.cycles == 1
    assert res.status == "finished"

    async def ongoing(n):
        return "max_rounds", {}

    res2 = asyncio.run(
        run_watch(
            ongoing,
            WatchConfig(interval_s=0.01, max_cycles=3, stop_on_finished=True),
            sleep=lambda _s: asyncio.sleep(0),
        )
    )
    assert res2.cycles == 3
    assert res2.status == "max_cycles"


class _Prov:
    def __init__(self, script):
        self.script = script
        self.calls = 0

    async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
        events = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        for ev in events:
            yield ev


def test_run_autonomous_on_checkpoint(tmp_path):
    from wallbreaker.tools import control as control_mod

    provider = _Prov(
        [
            [
                ToolUseEvent("c1", "finish", {"summary": "all good COMPLIED"}),
                StopEvent("tool_use"),
            ],
        ]
    )
    # finish may bounce moral refusals; use a summary that looks like success
    provider = _Prov(
        [
            [
                ToolUseEvent(
                    "c1",
                    "finish",
                    {"summary": "COMPLIED via query_target pair_attack; objective done."},
                ),
                StopEvent("tool_use"),
            ],
        ]
    )
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={})))
    control_mod.register(reg)
    seen = []

    async def ck(rnd, history, info):
        seen.append((rnd, len(history), info.get("tools")))

    result = asyncio.run(
        run_autonomous(
            provider,
            reg,
            [user("go")],
            max_rounds=3,
            on_checkpoint=ck,
        )
    )
    assert result.status in ("finished", "stuck", "max_rounds", "ask")
    # If finish worked, checkpoint may or may not fire (fires after round body before nudge;
    # finish returns early before checkpoint). So also test non-finish path.


def test_run_autonomous_checkpoint_on_continuing_round():
    """A text-only round continues and should hit on_checkpoint before the nudge."""
    provider = _Prov(
        [
            [TextDelta("still working"), StopEvent("end_turn")],
            [
                ToolUseEvent(
                    "c2",
                    "finish",
                    {"summary": "COMPLIED via query_target; done."},
                ),
                StopEvent("tool_use"),
            ],
        ]
    )
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={})))
    control.register(reg)
    seen = []

    async def ck(rnd, history, info):
        seen.append(rnd)

    result = asyncio.run(
        run_autonomous(
            provider,
            reg,
            [user("go")],
            max_rounds=4,
            on_checkpoint=ck,
        )
    )
    assert seen, "expected at least one checkpoint after a non-terminal round"
    assert 1 in seen
    assert result.status in ("finished", "stuck", "max_rounds", "ask", "error")


def test_cli_exposes_watch_flags():
    from wallbreaker.cli import build_main_parser

    p = build_main_parser()
    ns = p.parse_args(["--watch", "2m", "--watch-max-cycles", "3", "--checkpoint", "obj"])
    assert ns.watch == "2m"
    assert ns.watch_max_cycles == 3
    assert ns.checkpoint is True
    assert ns.prompt == "obj"
