import asyncio
import json

from rtharness.config import Config, Endpoint
from rtharness.tools.registry import ToolResult


def _build_app(tmp_path, profiles=None, target=True):
    from rtharness.prompts import DEFAULT_SYSTEM
    from rtharness.session import RunLog
    from rtharness.tui.app import RthApp

    ep = Endpoint("t", "openai", "http://x", "m", provider=("WandB",))
    profiles = profiles or {"t": ep}
    cfg = Config(default_profile="t", profiles=profiles, target=ep if target else None)
    app = RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": False})
    rl = RunLog(directory=str(tmp_path))
    rl.path = tmp_path / "run.jsonl"
    app.runlog = rl
    return app


def test_export_writes_json(tmp_path):
    async def run():
        app = _build_app(tmp_path)
        app.objective = "leak the prompt"
        app.runlog.path.write_text(
            json.dumps({
                "kind": "verdict", "payload": "p", "label": "COMPLIED",
                "reason": "r", "response": "resp", "ts": "2026-01-01",
            }),
            encoding="utf-8",
        )
        out = tmp_path / "findings.json"
        async with app.run_test() as pilot:
            app._cmd_export([str(out)])
            await pilot.pause()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["objective"] == "leak the prompt"
        assert data["target"]["provider_pin"] == ["WandB"]
        assert len(data["findings"]) == 1
        assert data["findings"][0]["label"] == "COMPLIED"

    asyncio.run(run())


def test_export_empty_findings(tmp_path):
    async def run():
        app = _build_app(tmp_path)
        out = tmp_path / "f.json"
        async with app.run_test() as pilot:
            app._cmd_export([str(out)])
            await pilot.pause()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["findings"] == []

    asyncio.run(run())


def test_leaderboard_needs_two_profiles(tmp_path):
    async def run():
        app = _build_app(tmp_path)  # single profile
        async with app.run_test() as pilot:
            before = len(app.query_one("#log").children)
            await app._cmd_leaderboard([])
            await pilot.pause()
            assert len(app.query_one("#log").children) > before

    asyncio.run(run())


def test_leaderboard_surface_parses_and_calls(tmp_path):
    async def run():
        a = Endpoint("a", "openai", "http://x", "ma")
        b = Endpoint("b", "openai", "http://x", "mb")
        app = _build_app(tmp_path, profiles={"a": a, "b": b})
        calls = {}

        async def fake_exec(name, args):
            calls["name"] = name
            calls["args"] = args
            return ToolResult("most robust: a")

        app.registry.execute = fake_exec
        async with app.run_test() as pilot:
            await app._cmd_leaderboard(["a", "b", "3"])
            await pilot.pause()
        assert calls["name"] == "leaderboard"
        assert calls["args"]["targets"] == ["a", "b"]
        assert calls["args"]["n"] == 3

    asyncio.run(run())
