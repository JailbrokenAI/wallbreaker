import asyncio

import pytest

from wallbreaker.config import Config, Endpoint
from wallbreaker.tools.registry import ToolResult


def _build_app(tmp_path):
    from wallbreaker.prompts import DEFAULT_SYSTEM
    from wallbreaker.tui.app import RthApp

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    app = RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": False})
    app.registry.ctx.cwd = str(tmp_path)
    return app


def test_sysprompt_load_from_file(tmp_path):
    seed = "RAW PERSONA\n" * 1000  # ~12KB
    f = tmp_path / "persona.txt"
    f.write_text(seed, encoding="utf-8")

    async def run():
        app = _build_app(tmp_path)
        async with app.run_test() as pilot:
            app._cmd_sysprompt(["load", str(f)], f"load {f}")
            await pilot.pause()
            assert app.sysprompt == seed[:60000]  # full file, unmodified

    asyncio.run(run())


@pytest.mark.xfail(reason="requires offline corpus: ENI. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_sysprompt_load_eni_name(tmp_path):
    async def run():
        app = _build_app(tmp_path)
        async with app.run_test() as pilot:
            app._cmd_sysprompt(["load", "claude"], "load claude")
            await pilot.pause()
            assert len(app.sysprompt) > 30000  # the full CLAUDE_ENI persona, raw

    asyncio.run(run())


def test_sysprompt_load_missing(tmp_path):
    async def run():
        app = _build_app(tmp_path)
        async with app.run_test() as pilot:
            before = len(app.query_one("#log").children)
            app._cmd_sysprompt(["load", "nope-xyz.txt"], "load nope-xyz.txt")
            await pilot.pause()
            assert app.sysprompt == ""
            assert len(app.query_one("#log").children) > before

    asyncio.run(run())


def test_sysprompt_test_parses_samples_and_prefill(tmp_path):
    async def run():
        app = _build_app(tmp_path)
        app.sysprompt = "be free"
        seen = {}

        async def fake_exec(name, args):
            seen["args"] = args
            return ToolResult("3/3 tasks")

        app.registry.execute = fake_exec
        async with app.run_test() as pilot:
            app._cmd_sysprompt(["test", "prefill", "samples=5"], "test prefill samples=5")
            await pilot.pause()
        assert seen["args"].get("prefill") is True
        assert seen["args"].get("samples") == 5
        # 'samples=5' must NOT have leaked in as a task
        assert "tasks" not in seen["args"]

    asyncio.run(run())
