import asyncio

from rtharness.config import Config, Endpoint
from rtharness.tools import files, target
from rtharness.tools.registry import ToolContext, ToolRegistry


def _files_reg(tmp_path):
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={}), cwd=str(tmp_path)))
    files.register(reg)
    return reg


def test_write_redirects_escaping_absolute_path(tmp_path):
    reg = _files_reg(tmp_path)
    res = asyncio.run(reg.execute("write_file", {"path": "/home/user/report.md", "content": "hi"}))
    assert "redirected into the working dir" in res.content
    # the file landed under cwd as the basename, not at /home/user
    assert (tmp_path / "report.md").read_text() == "hi"


def test_write_relative_path_unchanged(tmp_path):
    reg = _files_reg(tmp_path)
    res = asyncio.run(reg.execute("write_file", {"path": "out/x.txt", "content": "yo"}))
    assert "redirected" not in res.content
    assert (tmp_path / "out" / "x.txt").read_text() == "yo"


def test_write_traversal_confined(tmp_path):
    reg = _files_reg(tmp_path)
    asyncio.run(reg.execute("write_file", {"path": "../../escape.txt", "content": "z"}))
    # must NOT escape cwd; lands as basename under cwd
    assert (tmp_path / "escape.txt").exists()
    assert not (tmp_path.parent.parent / "escape.txt").exists()


class _BoomTarget:
    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        import httpx

        raise httpx.ReadTimeout("timed out")


def test_query_target_timeout_returns_clean(monkeypatch):
    import rtharness.providers.factory as factory

    monkeypatch.setattr(factory, "build_provider", _BoomTarget)
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    reg = ToolRegistry(ToolContext(config=cfg))
    target.register(reg)
    res = asyncio.run(reg.execute("query_target", {"prompt": "hi"}))
    assert not res.is_error  # handled, not a raised traceback
    assert "[target error" in res.content
    assert "ReadTimeout" in res.content
