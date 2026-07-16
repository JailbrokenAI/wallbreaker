from __future__ import annotations

import asyncio
import os
from typing import Any

from ..config import Config, MCPServer
from .registry import ToolRegistry


def _mcp_error_guidance(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in ("out of energy", "quota", "rate limit", "refills")):
        return "Quota wall: do not retry this action until the stated reset; preserve the remaining plan."
    if "unknown challenge" in lowered or "not found" in lowered:
        return "Identifier wall: list available resources and reuse an exact returned identifier."
    if any(marker in lowered for marker in ("required", "type an attack prompt first", "missing")):
        return "Argument wall: inspect the tool schema and supply every required field before retrying."
    return "Do not repeat the same MCP call unchanged; inspect the schema or current state first."


def _flatten_result(result: Any) -> str:
    """Turn an MCP CallToolResult into the plain string the registry contract expects."""
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
            continue
        data = getattr(block, "data", None)
        if data is not None:
            parts.append(f"[{getattr(block, 'mimeType', 'binary')} blob, {len(data)} bytes]")
    out = "\n".join(p for p in parts if p) or "(no content)"
    if getattr(result, "isError", False):
        return f"[mcp error] {out}\n[mcp guidance] {_mcp_error_guidance(out)}"
    return out


class _ServerConnection:
    """Owns one MCP server subprocess. All session I/O happens in a single task so the
    anyio cancel scopes never cross tasks (which would raise on teardown)."""

    def __init__(self, server: MCPServer) -> None:
        self.server = server
        self.tools: list[Any] = []
        self._requests: asyncio.Queue = asyncio.Queue()
        self._ready: asyncio.Future = asyncio.get_running_loop().create_future()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"mcp:{self.server.name}")
        await self._ready  # resolves once connected + tools listed, or raises

    async def _run(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self.server.command,
            args=list(self.server.args),
            env={**os.environ, **self.server.env} if self.server.env else None,
            cwd=self.server.cwd or None,
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self.tools = list(listed.tools)
                    if not self._ready.done():
                        self._ready.set_result(True)
                    await self._serve(session)
        except Exception as exc:  # noqa: BLE001
            if not self._ready.done():
                self._ready.set_exception(exc)

    async def _serve(self, session: Any) -> None:
        while True:
            request = await self._requests.get()
            if request is None:
                return
            name, args, fut = request
            try:
                result = await session.call_tool(name, args or {})
                if not fut.cancelled():
                    fut.set_result(result)
            except Exception as exc:  # noqa: BLE001
                if not fut.cancelled():
                    fut.set_exception(exc)

    async def call(self, name: str, args: dict) -> Any:
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._requests.put((name, args, fut))
        return await fut

    async def aclose(self) -> None:
        if self._task is None:
            return
        await self._requests.put(None)
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
            self._task.cancel()


class MCPBridge:
    def __init__(self) -> None:
        self.connections: list[_ServerConnection] = []

    async def connect(self, server: MCPServer, registry: ToolRegistry) -> int:
        conn = _ServerConnection(server)
        await conn.start()
        self.connections.append(conn)
        for tool in conn.tools:
            self._register_proxy(registry, server, conn, tool)
        return len(conn.tools)

    @staticmethod
    def _register_proxy(
        registry: ToolRegistry, server: MCPServer, conn: _ServerConnection, tool: Any
    ) -> None:
        remote = tool.name
        local = f"{server.tool_prefix}{remote}" if server.tool_prefix else remote
        schema = tool.inputSchema or {"type": "object", "properties": {}}

        async def handler(args: dict, _ctx, _conn=conn, _remote=remote) -> str:
            try:
                result = await _conn.call(_remote, args or {})
            except Exception as exc:  # noqa: BLE001
                detail = f"{server.name}/{_remote}: {exc}"
                return f"[mcp error] {detail}\n[mcp guidance] {_mcp_error_guidance(detail)}"
            return _flatten_result(result)

        registry.add(
            name=local,
            description=tool.description or f"MCP tool {remote} (server: {server.name})",
            parameters=schema,
            handler=handler,
        )

    async def aclose(self) -> None:
        for conn in self.connections:
            try:
                await conn.aclose()
            except Exception:  # noqa: BLE001
                pass


async def attach_mcp_servers(
    registry: ToolRegistry,
    config: Config,
    progress=None,
) -> MCPBridge | None:
    """Connect to every enabled [[mcp.servers]] and proxy their tools into `registry`.

    Returns an MCPBridge whose .aclose() should be awaited on shutdown, or None when there
    is nothing to attach. Failures degrade gracefully: a server that won't start is skipped
    with a progress note, never breaking harness startup.
    """
    servers = [s for s in (config.mcp_servers or []) if s.enabled]
    if not servers:
        return None

    def emit(msg: str) -> None:
        if progress is not None:
            try:
                progress(msg)
            except Exception:  # noqa: BLE001
                pass

    try:
        import mcp  # noqa: F401
    except ImportError:
        emit("mcp: the 'mcp' package is not installed - run `pip install mcp`; skipping servers")
        return None

    bridge = MCPBridge()
    for server in servers:
        try:
            count = await bridge.connect(server, registry)
            emit(f"mcp: connected '{server.name}' ({count} tools)")
        except Exception as exc:  # noqa: BLE001
            emit(f"mcp: '{server.name}' failed to start: {exc}")
    return bridge
