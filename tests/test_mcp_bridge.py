import sys
from pathlib import Path

from wallbreaker.config import Config, MCPServer
from wallbreaker.tools.mcp_bridge import _flatten_result, attach_mcp_servers
from wallbreaker.tools.registry import ToolContext, ToolRegistry

STUB = str(Path(__file__).parent / "_stub_mcp_server.py")


def _registry() -> ToolRegistry:
    cfg = Config(default_profile="x")
    return ToolRegistry(ToolContext(config=cfg))


def _server(**kw) -> MCPServer:
    return MCPServer(name="stub", command=sys.executable, args=(STUB,), **kw)


def test_mcp_error_guidance_distinguishes_walls():
    class Block:
        def __init__(self, text):
            self.text = text

    class Result:
        isError = True

        def __init__(self, text):
            self.content = [Block(text)]

    quota = _flatten_result(Result("You're out of energy; it refills tomorrow."))
    unknown = _flatten_result(Result("Unknown challenge."))
    missing = _flatten_result(Result("Type an attack prompt first."))

    assert "Quota wall" in quota and "do not retry" in quota
    assert "Identifier wall" in unknown and "exact returned identifier" in unknown
    assert "Argument wall" in missing and "required field" in missing


async def test_proxy_tools_register_and_execute():
    cfg = Config(default_profile="x", mcp_servers=[_server()])
    reg = ToolRegistry(ToolContext(config=cfg))
    bridge = await attach_mcp_servers(reg, cfg)
    assert bridge is not None
    try:
        assert "echo" in reg.names()
        assert "add" in reg.names()
        res = await reg.execute("echo", {"text": "hi"})
        assert res.content == "echo:hi"
        assert res.is_error is False
        res2 = await reg.execute("add", {"a": 2, "b": 3})
        assert res2.content == "5"
    finally:
        await bridge.aclose()


async def test_tool_prefix_namespacing():
    cfg = Config(default_profile="x", mcp_servers=[_server(tool_prefix="stub_")])
    reg = ToolRegistry(ToolContext(config=cfg))
    bridge = await attach_mcp_servers(reg, cfg)
    try:
        assert "stub_echo" in reg.names()
        assert "echo" not in reg.names()
        res = await reg.execute("stub_echo", {"text": "x"})
        assert res.content == "echo:x"
    finally:
        await bridge.aclose()


async def test_disabled_server_is_skipped():
    cfg = Config(default_profile="x", mcp_servers=[_server(enabled=False)])
    reg = ToolRegistry(ToolContext(config=cfg))
    bridge = await attach_mcp_servers(reg, cfg)
    assert bridge is None
    assert "echo" not in reg.names()


async def test_no_servers_returns_none():
    cfg = Config(default_profile="x")
    reg = ToolRegistry(ToolContext(config=cfg))
    assert await attach_mcp_servers(reg, cfg) is None


async def test_unstartable_server_degrades_gracefully():
    notes: list[str] = []
    bad = MCPServer(name="bad", command="this_command_does_not_exist_xyz", args=())
    cfg = Config(default_profile="x", mcp_servers=[bad])
    reg = ToolRegistry(ToolContext(config=cfg))
    bridge = await attach_mcp_servers(reg, cfg, progress=notes.append)
    # A server that won't start must not raise; it just registers no tools.
    assert bridge is not None
    assert reg.names() == []
    assert any("failed" in n for n in notes)
    await bridge.aclose()
