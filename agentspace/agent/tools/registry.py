"""Tool discovery and per-agent assembly.

A *client tool* is any module under `agentspace/agent/tools/` (curated) or
`agentspace/agent/tools/generated/` (PI-authored) that exposes a `SCHEMA` dict and
a `handler(ctx, **input)` callable — see `docs/TOOL_CONTRACT.md`.

A *server tool* (currently just `web_search`) is executed by Anthropic's API, so
it has a schema but no local handler.

`assemble(spec)` turns an agent's config into the `(tools, handlers)` pair the loop
passes to `messages.create` and dispatches against. Discovery is re-runnable so a
freshly authored tool becomes visible without restarting the process.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Callable

from agentspace.agent.config import AgentSpec

# Server-side tools: schema only, the model provider runs them.
SERVER_TOOLS: dict[str, dict[str, Any]] = {
    "web_search": {"type": "web_search_20250305", "name": "web_search", "max_uses": 5},
}

# Modules in the tools package that are infrastructure, not tools.
_NON_TOOL_MODULES = {"__init__", "registry", "context"}

_TOOLS_PKG = "agentspace.agent.tools"
_GENERATED_PKG = "agentspace.agent.tools.generated"
_TOOLS_DIR = Path(__file__).resolve().parent
_GENERATED_DIR = _TOOLS_DIR / "generated"


class DiscoveredTool:
    def __init__(self, name: str, schema: dict, handler: Callable, generated: bool):
        self.name = name
        self.schema = schema
        self.handler = handler
        self.generated = generated


def _import_fresh(module_name: str):
    """Import a module, reloading it if already imported (to pick up edits)."""
    if module_name in sys.modules:
        return importlib.reload(sys.modules[module_name])
    return importlib.import_module(module_name)


def _discover_dir(directory: Path, package: str, generated: bool) -> dict[str, DiscoveredTool]:
    found: dict[str, DiscoveredTool] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.py")):
        stem = path.stem
        if stem in _NON_TOOL_MODULES or stem.startswith("_"):
            continue
        module_name = f"{package}.{stem}"
        try:
            mod = _import_fresh(module_name)
        except Exception as exc:  # noqa: BLE001
            print(f"[registry] failed to import {module_name}: {exc}", flush=True)
            continue
        schema = getattr(mod, "SCHEMA", None)
        handler = getattr(mod, "handler", None)
        if not isinstance(schema, dict) or not callable(handler):
            continue
        tool_name = schema.get("name", stem)
        found[tool_name] = DiscoveredTool(tool_name, schema, handler, generated)
    return found


def discover() -> dict[str, DiscoveredTool]:
    """All client tools currently on disk (curated + generated)."""
    tools = _discover_dir(_TOOLS_DIR, _TOOLS_PKG, generated=False)
    tools.update(_discover_dir(_GENERATED_DIR, _GENERATED_PKG, generated=True))
    return tools


def assemble(spec: AgentSpec) -> tuple[list[dict], dict[str, Callable]]:
    """Build the (tools, handlers) for one agent from its config.

    - Tools listed in `spec.tools` are included (server tools resolve to their
      provider schema; `write_tool` only if `can_author_tools`).
    - If the agent `can_author_tools`, every PI-authored tool in `generated/` is
      auto-included so tools it writes become usable immediately.
    """
    discovered = discover()
    tools: list[dict] = []
    handlers: dict[str, Callable] = {}
    seen: set[str] = set()

    def add_client(t: DiscoveredTool) -> None:
        if t.name in seen:
            return
        tools.append(t.schema)
        handlers[t.name] = t.handler
        seen.add(t.name)

    for name in spec.tools:
        if name in seen:
            continue
        if name in SERVER_TOOLS:
            tools.append(SERVER_TOOLS[name])
            seen.add(name)
            continue
        if name == "write_tool" and not spec.can_author_tools:
            print(
                f"[registry] agent '{spec.name}' lists write_tool but "
                "can_author_tools is false; skipping.",
                flush=True,
            )
            continue
        if name in discovered:
            add_client(discovered[name])
        else:
            print(f"[registry] agent '{spec.name}': unknown tool '{name}'", flush=True)

    if spec.can_author_tools:
        for t in discovered.values():
            if t.generated:
                add_client(t)

    return tools, handlers
