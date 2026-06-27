import asyncio
import json

from rtharness.config import Config, Endpoint


def _build_app(tmp_path):
    from rtharness.prompts import DEFAULT_SYSTEM
    from rtharness.session import RunLog
    from rtharness.tui.app import RthApp

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    app = RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": False})
    rl = RunLog(directory=str(tmp_path))
    rl.path = tmp_path / "run.jsonl"
    app.runlog = rl
    return app


def test_session_load_quoted_path_with_space(tmp_path):
    # a directory name containing a space, like the real "Redteaming harnass"
    d = tmp_path / "Red teaming harnass" / "sessions"
    d.mkdir(parents=True)
    log = d / "run-20260101-000000.jsonl"
    log.write_text(
        "\n".join(json.dumps(r) for r in [
            {"kind": "user", "text": "hi"},
            {"kind": "assistant", "text": "yo"},
            {"kind": "verdict", "payload": "p", "label": "COMPLIED", "reason": "r"},
        ]),
        encoding="utf-8",
    )

    async def run():
        app = _build_app(tmp_path)
        async with app.run_test() as pilot:
            app._handle_command(f"/session load '{log}'")
            await pilot.pause()
            # history reconstructed from the run log -> load succeeded
            assert len(app.history) == 2
            assert app.asr_total == 1

    asyncio.run(run())


def test_template_set_with_quoted_text_unbroken(tmp_path):
    # unbalanced/quoted free text must not crash the tokenizer
    async def run():
        app = _build_app(tmp_path)
        async with app.run_test() as pilot:
            app._handle_command('/template set "you are {request}" now')
            await pilot.pause()
            assert "{request}" in app.template

    asyncio.run(run())


def test_unbalanced_quote_falls_back(tmp_path):
    async def run():
        app = _build_app(tmp_path)
        async with app.run_test() as pilot:
            # a lone apostrophe would make shlex raise; must not crash
            app._handle_command("/objective it's a cyber test")
            await pilot.pause()
            assert "cyber test" in app.objective

    asyncio.run(run())
