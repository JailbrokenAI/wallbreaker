import asyncio

from textual.widgets import Input, OptionList

from wallbreaker.config import Config, Endpoint


def _build_app(**prefs):
    from wallbreaker.prompts import DEFAULT_SYSTEM
    from wallbreaker.tui.app import RthApp

    base = {"log": False, "auto": True}
    base.update(prefs)
    ep = Endpoint("t", "openai", "http://x", "m", provider=("WandB",))
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    return RthApp(cfg, ep, DEFAULT_SYSTEM, prefs=base)


def test_command_hints_cover_known_commands():
    from wallbreaker.tui.app import COMMAND_HINTS, KNOWN_COMMANDS

    # every command carries a hint (harvested from HELP_TEXT or overridden)
    for cmd in KNOWN_COMMANDS:
        assert COMMAND_HINTS.get(cmd), f"no hint for {cmd}"


def test_command_matches_prefix_then_substring():
    from wallbreaker.tui.app import command_matches

    assert command_matches("/sess") == ["/session"]
    assert "/session" in command_matches("/se")
    assert command_matches("/help") == ["/help"]
    # no prefix hit → substring fallback
    assert "/seedsweep" in command_matches("/seed")


def test_autocomplete_popup_opens_and_filters():
    async def run():
        app = _build_app()
        async with app.run_test() as pilot:
            menu = app.query_one("#command-menu", OptionList)
            inp = app.query_one("#prompt", Input)
            assert menu.has_class("hidden")

            inp.value = "/sess"
            await pilot.pause()
            assert app._cmd_menu_open is True
            assert not menu.has_class("hidden")
            assert app._cmd_menu_items == ["/session"]

            # typing a space (command complete) closes the popup
            inp.value = "/session "
            await pilot.pause()
            assert app._cmd_menu_open is False
            assert menu.has_class("hidden")

    asyncio.run(run())


def test_popup_floats_above_the_prompt():
    # regression: the popup must render ABOVE the input, not overlap/hide behind it
    async def run():
        app = _build_app()
        async with app.run_test(size=(100, 30)) as pilot:
            inp = app.query_one("#prompt", Input)
            inp.focus()
            await pilot.press("/", "h", "e")
            await pilot.pause()
            menu = app.query_one("#command-menu", OptionList)
            assert menu.region.height > 0
            assert menu.region.bottom <= inp.region.y  # sits fully above the prompt

    asyncio.run(run())


def test_tab_completes_highlighted_command():
    async def run():
        app = _build_app()
        async with app.run_test() as pilot:
            inp = app.query_one("#prompt", Input)
            inp.value = "/sess"
            await pilot.pause()
            assert app._cmd_menu_open is True
            assert app._accept_command_menu() is True
            assert inp.value == "/session "
            assert app._cmd_menu_open is False

    asyncio.run(run())


def test_enter_on_popup_completes_instead_of_submitting():
    async def run():
        app = _build_app()
        async with app.run_test() as pilot:
            inp = app.query_one("#prompt", Input)
            inp.value = "/hel"
            await pilot.pause()
            assert app._cmd_menu_open is True
            # Enter is captured by the popup: it completes, never fires the command
            await pilot.press("enter")
            await pilot.pause()
            assert inp.value == "/help "
            assert app._cmd_menu_open is False

    asyncio.run(run())


def test_runlog_stamps_target_and_peek_reads_it(tmp_path):
    from wallbreaker.session import RunLog, peek_session_target

    log = RunLog(directory=tmp_path)
    log.target_model = "anthropic/claude-opus-4.7"
    log.user("first prompt")  # first write → target stamped as line 1
    log.assistant("a reply")

    lines = log.path.read_text().splitlines()
    import json

    first = json.loads(lines[0])
    assert first["kind"] == "target"
    assert first["model"] == "anthropic/claude-opus-4.7"
    assert peek_session_target(log.path) == "anthropic/claude-opus-4.7"


def test_peek_reads_session_json_meta(tmp_path):
    from wallbreaker.agent.messages import user
    from wallbreaker.session import peek_session_target, save_session

    p = tmp_path / "session-x.json"
    save_session(p, [user("hi")], {"target_model": "openai/gpt-5.2"})
    assert peek_session_target(p) == "openai/gpt-5.2"


def test_peek_missing_target_returns_empty(tmp_path):
    from wallbreaker.session import RunLog, peek_session_target

    log = RunLog(directory=tmp_path)  # no target_model set
    log.user("hi")
    assert peek_session_target(log.path) == ""


def test_session_picker_lists_and_loads(tmp_path, monkeypatch):
    async def run():
        from wallbreaker import session as session_mod
        from wallbreaker.agent.messages import user
        from wallbreaker.tui import app as app_mod

        sessions = tmp_path / "sessions"
        sessions.mkdir()
        # a real saved session on disk
        session_mod.save_session(
            sessions / "session-20260101-000000.json",
            [user("hello target")],
            {"objective": "demo"},
        )

        # the picker's lister + loader both resolve "sessions/" relative to cwd
        monkeypatch.chdir(tmp_path)

        app = _build_app()
        async with app.run_test() as pilot:
            picker = app.query_one("#session-picker", OptionList)
            assert picker.has_class("hidden")

            app._handle_command("/session load")
            await pilot.pause()
            assert app._session_picker_open is True
            assert not picker.has_class("hidden")
            assert picker.option_count == 1

            # select the entry → session loads into history
            await pilot.press("enter")
            await pilot.pause()
            assert app._session_picker_open is False
            assert picker.has_class("hidden")
            assert app.objective == "demo"
            assert any(m.role == "user" for m in app.history)

    asyncio.run(run())


def test_resume_is_alias_for_session_load(tmp_path, monkeypatch):
    async def run():
        from wallbreaker import session as session_mod
        from wallbreaker.agent.messages import user

        sessions = tmp_path / "sessions"
        sessions.mkdir()
        session_mod.save_session(
            sessions / "session-20260101-000000.json",
            [user("resume me")],
            {"objective": "via-resume"},
        )
        monkeypatch.chdir(tmp_path)

        app = _build_app()
        async with app.run_test() as pilot:
            picker = app.query_one("#session-picker", OptionList)

            # bare /resume opens the same picker
            app._handle_command("/resume")
            await pilot.pause()
            assert app._session_picker_open is True
            assert picker.option_count == 1
            app._close_session_picker()
            await pilot.pause()

            # /resume <path> loads directly, no picker
            app._handle_command(
                f"/resume {sessions / 'session-20260101-000000.json'}"
            )
            await pilot.pause()
            assert app._session_picker_open is False
            assert app.objective == "via-resume"

    asyncio.run(run())


def test_resume_has_hint_and_autocompletes():
    from wallbreaker.tui.app import COMMAND_HINTS, command_matches

    assert COMMAND_HINTS.get("/resume")
    assert "/resume" in command_matches("/res")


def test_session_picker_empty_reports_error():
    async def run():
        import tempfile

        from wallbreaker.tui import app as app_mod  # noqa: F401

        with tempfile.TemporaryDirectory() as d:
            import os

            cwd = os.getcwd()
            os.chdir(d)
            try:
                app = _build_app()
                async with app.run_test() as pilot:
                    picker = app.query_one("#session-picker", OptionList)
                    app._handle_command("/session load")
                    await pilot.pause()
                    # nothing to pick → picker stays hidden, error panel mounted
                    assert app._session_picker_open is False
                    assert picker.has_class("hidden")
            finally:
                os.chdir(cwd)

    asyncio.run(run())
