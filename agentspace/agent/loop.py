"""The agentic loop — the educational core of AgentSpace.

Hand-written against the raw Anthropic Messages API (no agent SDK), so every part
of the tool-use cycle is visible:

    load history → call messages.create → if the model wants a tool, run it and
    feed the result back → repeat until the model stops → persist the session.

Two details worth noting:
- `web_search` is a *server* tool: Anthropic runs it and returns results inline,
  so we never dispatch it locally — we only handle client tools (`sh`,
  `load_skill`, `write_tool`, and any PI-authored tool).
- After a `write_tool` call we RE-ASSEMBLE the toolset mid-conversation, so a
  tool the agent just authored is callable on its very next turn.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import replace
from pathlib import Path

from agentspace.agent.config import AgentSpec
from agentspace.agent.mcp_client import MCPManager
from agentspace.agent.sessions import SessionStore
from agentspace.agent.tools import registry
from agentspace.agent.tools.context import ToolContext
from agentspace.agent.tools.skills import skills_catalog
from agentspace.common import paths

MAX_ITERATIONS = 24


class Agent:
    def __init__(self, spec: AgentSpec, root: Path):
        self.spec = spec
        self.root = root
        self.sessions = SessionStore(paths.agent_runtime_dir(root, spec.name))
        self.skills_dir = paths.skills_dir(root)
        workdir = root if not spec.workdir else (root / spec.workdir)
        self.ctx = ToolContext(
            root=root,
            workdir=workdir.resolve(),
            skills_dir=self.skills_dir,
            allowed_skills=list(spec.skills),
            agent_name=spec.name,
            output_dir=paths.output_dir(root),
        )
        # Connect MCP servers once (reused across runs). Empty list → no-op.
        self.mcp = MCPManager(spec.mcp_servers, root)
        self._client = None

    def _assemble(self):
        """Native tools (registry) + this agent's MCP tools, as one (tools, handlers)."""
        tools, handlers = registry.assemble(self.spec)
        tools = tools + self.mcp.tool_schemas
        handlers = {**handlers, **self.mcp.handlers}
        return tools, handlers

    # -- model client (lazy so the server can start without a key) -----------
    def _get_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def _system_prompt(self) -> str:
        catalog = skills_catalog(self.skills_dir, self.spec.skills)
        return self.spec.system_prompt + catalog

    # -- the loop ------------------------------------------------------------
    def run(self, user_input: str, session_id: str | None, emit=None) -> dict:
        """Run one turn. `emit(kind, text)` receives progress events (model turns,
        tool calls, completion) so the host can show live status."""
        emit = emit or (lambda *a, **k: None)

        if not os.environ.get("ANTHROPIC_API_KEY"):
            emit("error", "ANTHROPIC_API_KEY is not set")
            return self._error_response(
                session_id,
                "ANTHROPIC_API_KEY is not set in this agent's environment. Export it "
                "before starting the host so agents can call the Messages API.",
            )

        if not session_id:
            session_id = self.sessions.new_id()
        messages = self.sessions.load(session_id)
        messages.append({"role": "user", "content": user_input})

        tools, handlers = self._assemble()
        system = self._system_prompt()
        # A per-run context whose progress() streams interim tool output as events.
        ctx = replace(self.ctx, progress=lambda text: emit("progress", text))
        usage = {"input_tokens": 0, "output_tokens": 0, "iterations": 0, "tool_calls": 0}
        emit("start", f"received: {user_input[:80]}")

        try:
            for _ in range(MAX_ITERATIONS):
                usage["iterations"] += 1
                emit("model", f"turn {usage['iterations']}: thinking…")
                kwargs = dict(
                    model=self.spec.model,
                    max_tokens=self.spec.max_tokens,
                    system=system,
                    messages=messages,
                )
                if tools:
                    kwargs["tools"] = tools

                resp = self._get_client().messages.create(**kwargs)
                usage["input_tokens"] += resp.usage.input_tokens
                usage["output_tokens"] += resp.usage.output_tokens

                messages.append(
                    {"role": "assistant", "content": [b.model_dump() for b in resp.content]}
                )
                self._emit_assistant_progress(emit, resp.content)

                if resp.stop_reason != "tool_use":
                    break

                tool_results = []
                wrote_tool = False
                for block in resp.content:
                    if block.type != "tool_use":
                        continue  # server tools (web_search) are already executed
                    usage["tool_calls"] += 1
                    if block.name == "write_tool":
                        wrote_tool = True
                    emit("tool", f"{block.name}({_compact(dict(block.input))})")
                    result = self._dispatch(ctx, handlers, block.name, dict(block.input))
                    emit("tool_done", f"{block.name} → {result[:80]}")
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )

                messages.append({"role": "user", "content": tool_results})

                # A freshly authored tool must become callable this turn.
                if wrote_tool:
                    tools, handlers = self._assemble()
                    emit("system", "reloaded tools — newly authored tool now available")
            else:
                messages.append(
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": f"[stopped after {MAX_ITERATIONS} tool iterations]",
                            }
                        ],
                    }
                )
        except Exception as exc:  # noqa: BLE001
            emit("error", str(exc))
            return self._error_response(session_id, f"agent error: {exc}", usage)

        self.sessions.save(session_id, messages)
        final = messages[-1]["content"]
        emit("done", _text_of(final)[:120])
        return {
            "id": "resp_" + uuid.uuid4().hex[:12],
            "session_id": session_id,
            "model": self.spec.model,
            "output_text": _text_of(final),
            "output": final,
            "usage": usage,
        }

    @staticmethod
    def _emit_assistant_progress(emit, content) -> None:
        """Surface any text the model produced alongside its tool calls."""
        for block in content:
            if getattr(block, "type", None) == "text":
                text = (block.text or "").strip()
                if text:
                    emit("say", text[:120])

    def _dispatch(self, ctx, handlers, name: str, tool_input: dict) -> str:
        handler = handlers.get(name)
        if handler is None:
            return f"ERROR: tool '{name}' is not available."
        try:
            print(f"[tool] {name}({tool_input})", flush=True)
            result = handler(ctx, **tool_input)
            return result if isinstance(result, str) else str(result)
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: tool '{name}' raised: {exc}"

    def _error_response(self, session_id, message: str, usage: dict | None = None) -> dict:
        return {
            "id": "resp_" + uuid.uuid4().hex[:12],
            "session_id": session_id or "",
            "model": self.spec.model,
            "output_text": f"ERROR: {message}",
            "output": [{"type": "text", "text": f"ERROR: {message}"}],
            "usage": usage or {},
        }


def _text_of(content) -> str:
    """Join the text blocks of an assistant content list."""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts).strip()


def _compact(d: dict, limit: int = 70) -> str:
    """Render tool input compactly for a status line."""
    s = ", ".join(f"{k}={str(v)[:40]!r}" for k, v in d.items())
    return s[:limit] + ("…" if len(s) > limit else "")
