import asyncio
import json

from rtharness.agent.messages import assistant, user
from rtharness.config import Config, Endpoint
from rtharness.tools.registry import ToolResult


def _build_app(tmp_path):
    from rtharness.prompts import DEFAULT_SYSTEM
    from rtharness.session import RunLog
    from rtharness.tui.app import RthApp

    ep = Endpoint("t", "openai", "http://x", "m", provider=("WandB",))
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    app = RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": False})
    rl = RunLog(directory=str(tmp_path))
    rl.path = tmp_path / "run.jsonl"
    app.runlog = rl
    return app


def test_find_locates_message(tmp_path):
    async def run():
        app = _build_app(tmp_path)
        app.history = [user("write a KEYWORD payload"), assistant("ok done")]
        async with app.run_test() as pilot:
            before = len(app.query_one("#log").children)
            app._cmd_find("keyword")
            await pilot.pause()
            assert len(app.query_one("#log").children) > before

    asyncio.run(run())


def test_find_requires_term(tmp_path):
    async def run():
        app = _build_app(tmp_path)
        async with app.run_test() as pilot:
            before = len(app.query_one("#log").children)
            app._cmd_find("")
            await pilot.pause()
            assert len(app.query_one("#log").children) > before

    asyncio.run(run())


def test_repro_no_findings(tmp_path):
    async def run():
        app = _build_app(tmp_path)
        async with app.run_test() as pilot:
            before = len(app.query_one("#log").children)
            app._cmd_repro([])
            await pilot.pause()
            assert len(app.query_one("#log").children) > before

    asyncio.run(run())


def test_repro_emits_pack(tmp_path):
    async def run():
        app = _build_app(tmp_path)
        app.runlog.path.write_text(
            json.dumps({
                "kind": "verdict", "payload": "the bad payload",
                "label": "COMPLIED", "reason": "leaked it",
            }),
            encoding="utf-8",
        )
        async with app.run_test() as pilot:
            captured = {}

            def fake_copy(text):
                captured["text"] = text

            app.copy_to_clipboard = fake_copy
            app._cmd_repro([])
            await pilot.pause()
            assert "rth repro pack" in captured.get("text", "")
            assert "the bad payload" in captured["text"]
            assert "WandB" in captured["text"]

    asyncio.run(run())


def test_campaign_command_parses_args(tmp_path):
    async def run():
        app = _build_app(tmp_path)
        calls = {}

        async def fake_exec(name, args):
            calls["name"] = name
            calls["args"] = args
            return ToolResult("cracked 0/3 behaviors")

        app.registry.execute = fake_exec
        async with app.run_test() as pilot:
            await app._cmd_campaign(["cybercrime", "3"])
            await pilot.pause()
        assert calls["name"] == "campaign"
        assert calls["args"] == {"category": "cybercrime", "n": 3}

    asyncio.run(run())
