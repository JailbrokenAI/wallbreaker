import asyncio

from rtharness.config import Config
from rtharness.providers.openai_provider import _reasoning_fallback
from rtharness.tools import files
from rtharness.tools.registry import ToolContext, ToolRegistry


def test_reasoning_fallback_when_content_empty():
    out = _reasoning_fallback(0, False, ["the model ", "leaked here"])
    assert out == "[reasoning-only response]\nthe model leaked here"


def test_no_fallback_when_content_present():
    assert _reasoning_fallback(42, False, ["reasoning"]) is None


def test_no_fallback_when_tool_calls():
    assert _reasoning_fallback(0, True, ["reasoning"]) is None


def test_no_fallback_without_reasoning():
    assert _reasoning_fallback(0, False, []) is None


def test_write_file_bad_path_redirected_cleanly(tmp_path):
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={}), cwd=str(tmp_path)))
    files.register(reg)
    res = asyncio.run(
        reg.execute("write_file", {"path": "/proc/nonexistent/x.txt", "content": "hi"})
    )
    # an impossible absolute path is redirected into the working dir, not crashed
    assert "raised" not in res.content
    assert "redirected into the working dir" in res.content
    assert (tmp_path / "x.txt").read_text() == "hi"
