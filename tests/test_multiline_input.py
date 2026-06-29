import asyncio

from textual import events
from textual.widgets import Input

from rtharness.config import Config, Endpoint
from rtharness.prompts import DEFAULT_SYSTEM
from rtharness.tui.app import PromptInput, RthApp


def _build_app():
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    return RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": False, "auto": True})


def test_prompt_is_input_subclass():
    # query_one('#prompt', Input) contract must still hold
    assert issubclass(PromptInput, Input)


def test_multiline_paste_buffers_all_lines():
    async def run():
        app = _build_app()
        async with app.run_test() as pilot:
            inp = app.query_one("#prompt", Input)
            assert isinstance(inp, PromptInput)
            inp._on_paste(events.Paste("line one\nline two\nline three"))
            await pilot.pause()
            assert inp.buffer == ["line one", "line two"]
            assert inp.value == "line three"
            assert inp.full_text() == "line one\nline two\nline three"

    asyncio.run(run())


def test_paste_dispatch_does_not_duplicate():
    # Regression: Textual dispatches _on_paste to every class in the MRO, so without
    # prevent_default() the base Input._on_paste fires too and inserts the text twice.
    async def run():
        app = _build_app()
        async with app.run_test() as pilot:
            inp = app.query_one("#prompt", Input)
            inp.focus()
            inp.post_message(events.Paste("hello world"))
            await pilot.pause()
            await pilot.pause()
            assert inp.full_text() == "hello world"  # not "hello worldhello world"

    asyncio.run(run())


def test_multiline_paste_dispatch_not_duplicated():
    async def run():
        app = _build_app()
        async with app.run_test() as pilot:
            inp = app.query_one("#prompt", Input)
            inp.focus()
            inp.post_message(events.Paste("alpha\nbravo\ncharlie"))
            await pilot.pause()
            await pilot.pause()
            assert inp.full_text() == "alpha\nbravo\ncharlie"
            assert inp.buffer == ["alpha", "bravo"]

    asyncio.run(run())


def test_single_line_paste_unbuffered():
    async def run():
        app = _build_app()
        async with app.run_test() as pilot:
            inp = app.query_one("#prompt", Input)
            inp._on_paste(events.Paste("just one line"))
            await pilot.pause()
            assert inp.buffer == []
            assert inp.value == "just one line"
            assert inp.full_text() == "just one line"

    asyncio.run(run())


def test_crlf_paste_normalized():
    async def run():
        app = _build_app()
        async with app.run_test() as pilot:
            inp = app.query_one("#prompt", Input)
            inp._on_paste(events.Paste("a\r\nb\r\nc"))
            await pilot.pause()
            assert inp.full_text() == "a\nb\nc"

    asyncio.run(run())


def test_soft_newline_builds_multiline():
    async def run():
        app = _build_app()
        async with app.run_test() as pilot:
            inp = app.query_one("#prompt", Input)
            inp.value = "first"
            inp.soft_newline()
            inp.value = "second"
            await pilot.pause()
            assert inp.buffer == ["first"]
            assert inp.full_text() == "first\nsecond"

    asyncio.run(run())


def test_multiline_submits_as_one_message():
    async def run():
        app = _build_app()
        app._busy = True  # routes submit into the steer queue, no agent worker
        async with app.run_test() as pilot:
            inp = app.query_one("#prompt", Input)
            inp._on_paste(events.Paste("Target is gpt-5.5.\nRun the battery.\nReport ASR."))
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app._pending_feedback == [
                "Target is gpt-5.5.\nRun the battery.\nReport ASR."
            ]
            # buffer cleared after submit
            assert inp.buffer == []
            assert inp.value == ""

    asyncio.run(run())


def test_history_nav_skipped_during_multiline_compose():
    async def run():
        app = _build_app()
        app._input_history = ["old message"]
        async with app.run_test() as pilot:
            inp = app.query_one("#prompt", Input)
            inp.focus()
            inp._on_paste(events.Paste("draft line 1\ndraft line 2"))
            await pilot.pause()
            await pilot.press("up")  # must NOT overwrite the compose with history
            await pilot.pause()
            assert inp.value == "draft line 2"
            assert inp.buffer == ["draft line 1"]

    asyncio.run(run())
