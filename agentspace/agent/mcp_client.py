"""MCP integration — let agents use Model Context Protocol servers as tools.

Each agent process can connect to one or more MCP servers (declared in
`mcp/servers.yaml`, referenced by name in the agent's `mcp_servers:`). Their tools are
converted to Anthropic tool schemas (name-prefixed `mcp__<server>__<tool>`) and merged
into the same `(tools, handlers)` the loop already dispatches — so to the rest of the
system an MCP tool looks like any other tool.

The MCP SDK is async; our loop is sync. We run ONE asyncio event loop in a background
thread and bridge calls with `run_coroutine_threadsafe`. The connection lifecycle lives
entirely inside a single long-lived `_serve()` coroutine (anyio requires the async
context managers to be entered and exited in the same task), which opens the servers,
signals ready, waits, then closes.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
from contextlib import AsyncExitStack
from pathlib import Path

import yaml

from agentspace.common import paths

_ENV = re.compile(r"\$\{(\w+)\}")
CONNECT_TIMEOUT = 45
CALL_TIMEOUT = 120
MAX_RESULT_CHARS = 16000


def _expand(value):
    """Recursively expand ${ENV_VAR} in strings within a config value."""
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def load_catalog(root: Path) -> dict:
    f = paths.mcp_servers_file(root)
    if not f.exists():
        return {}
    data = yaml.safe_load(f.read_text()) or {}
    return data.get("servers", {}) or {}


class MCPManager:
    """Connects to an agent's MCP servers and exposes their tools."""

    def __init__(self, server_names, root: Path, log=None):
        self.root = root
        self.names = list(server_names or [])
        self._log = log or (lambda t: print(f"[mcp] {t}", flush=True))
        self._loop = None
        self._thread = None
        self._serve_fut = None
        self._ready = threading.Event()
        self._stop = None
        self._stack = None
        self._sessions = {}        # server -> ClientSession
        self._schemas = []         # anthropic tool schemas
        self._handlers = {}        # prefixed name -> handler(ctx, **input)
        self._index = {}           # prefixed name -> (server, raw_tool_name)
        if self.names:
            self._start()

    # -- public API ----------------------------------------------------------
    @property
    def tool_schemas(self) -> list[dict]:
        return list(self._schemas)

    @property
    def handlers(self) -> dict:
        return dict(self._handlers)

    def status(self) -> dict:
        """server name -> connected?"""
        return {n: (n in self._sessions) for n in self.names}

    def close(self) -> None:
        if not self._loop or not self._loop.is_running():
            return
        if self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        try:
            if self._serve_fut:
                self._serve_fut.result(timeout=10)
        except Exception:  # noqa: BLE001
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)

    # -- background loop -----------------------------------------------------
    def _start(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._serve_fut = asyncio.run_coroutine_threadsafe(self._serve(), self._loop)
        if not self._ready.wait(timeout=CONNECT_TIMEOUT + 15):
            self._log("timed out waiting for servers to connect")

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _serve(self) -> None:
        self._stop = asyncio.Event()
        self._stack = AsyncExitStack()
        catalog = load_catalog(self.root)
        for name in self.names:
            cfg = catalog.get(name)
            if not cfg:
                self._log(f"server '{name}' not in catalog; skipping")
                continue
            if cfg.get("enabled") is False:
                self._log(f"server '{name}' disabled; skipping")
                continue
            try:
                await asyncio.wait_for(self._connect_one(name, _expand(cfg)), CONNECT_TIMEOUT)
            except Exception as exc:  # noqa: BLE001
                self._log(f"server '{name}' failed: {exc}")
        self._ready.set()
        try:
            await self._stop.wait()
        finally:
            try:
                await self._stack.aclose()
            except Exception:  # noqa: BLE001
                pass

    async def _connect_one(self, name: str, cfg: dict) -> None:
        from mcp import ClientSession, StdioServerParameters

        if cfg.get("url"):
            from mcp.client.streamable_http import streamablehttp_client

            streams = await self._stack.enter_async_context(
                streamablehttp_client(cfg["url"], headers=cfg.get("headers") or {})
            )
            read, write = streams[0], streams[1]
        else:
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(
                command=cfg["command"],
                args=cfg.get("args") or [],
                env={**os.environ, **(cfg.get("env") or {})},
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))

        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._sessions[name] = session

        result = await session.list_tools()
        for tool in result.tools:
            pname = f"mcp__{name}__{tool.name}"
            self._schemas.append(
                {
                    "name": pname,
                    "description": (tool.description or f"{name}: {tool.name}")[:1000],
                    "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
                }
            )
            self._index[pname] = (name, tool.name)
            self._handlers[pname] = self._make_handler(pname)
        self._log(f"connected '{name}' ({len(result.tools)} tools)")

    def _make_handler(self, pname: str):
        def handler(ctx, **kwargs):
            server, raw = self._index[pname]
            if getattr(ctx, "progress", None):
                ctx.progress(f"mcp: {server}.{raw}(...)")
            return self.call(server, raw, kwargs)

        return handler

    # -- sync bridge to async call_tool --------------------------------------
    def call(self, server: str, tool: str, args: dict) -> str:
        if not self._loop:
            return "ERROR: MCP not running"
        fut = asyncio.run_coroutine_threadsafe(self._call(server, tool, args), self._loop)
        try:
            return fut.result(timeout=CALL_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: MCP call {server}.{tool} failed: {exc}"

    async def _call(self, server: str, tool: str, args: dict) -> str:
        session = self._sessions.get(server)
        if not session:
            return f"ERROR: MCP server '{server}' not connected"
        result = await session.call_tool(tool, arguments=args or {})
        parts = []
        for block in result.content or []:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
            else:
                parts.append(f"[{getattr(block, 'type', 'content')}]")
        text = "\n".join(parts).strip() or "(no content)"
        if getattr(result, "isError", False):
            return f"ERROR (tool): {text}"
        return text[:MAX_RESULT_CHARS]
