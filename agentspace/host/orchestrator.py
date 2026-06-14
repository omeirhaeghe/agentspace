"""The conductor — natural-language orchestration over the agent registry.

The host hands a free-text goal to the conductor, an LLM planning loop with two
tools:

  - list_agents : discover the available agents (name, description, tools, status)
  - run_agent   : delegate a sub-task to an agent (auto-starts it), stream its
                  progress, and return its reply

The conductor breaks the goal into steps, picks the best-suited agent for each,
chains them (feeding one agent's output into the next), and writes a final summary.
This is the one place the *host* calls a model; individual agents still run as their
own processes.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from agentspace.host import agent_factory, registry

CONDUCTOR_PROMPT = """\
You are the AgentSpace conductor — the orchestration brain of a local agent runtime.
The user gives you a goal in natural language; you accomplish it by delegating to
specialized agents.

How to work:
1. Consider the available agents (roster below; call list_agents for live details).
2. Break the goal into steps and delegate each with run_agent to the best-suited
   agent. The agent does NOT see this conversation — put ALL context it needs
   (including results from previous steps) into the `task` text.
3. Chain agents when useful: feed one agent's reply into the next agent's task.
4. When finished, write a short, clear final summary for the user. Mention any files
   that were created and where.

Guidelines:
- Match agents by their description and tools. Prefer existing agents.
- If NO existing agent fits the goal, use create_agent to build a suitable one, then
  delegate to it with run_agent.
- If an agent isn't running, run_agent starts it automatically.
- Keep each delegated task specific and self-contained.
- Don't over-delegate: simple questions may need just one agent (or a direct answer).
"""

TOOLS = [
    {
        "name": "list_agents",
        "description": "List available agents with their descriptions, tools, and running status.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_agent",
        "description": (
            "Delegate a task to an agent and get its reply. Starts the agent if "
            "needed. The agent does not see prior conversation — include all needed "
            "context in `task`."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "Agent name from list_agents."},
                "task": {"type": "string", "description": "Self-contained task with full context."},
            },
            "required": ["agent", "task"],
        },
    },
    {
        "name": "create_agent",
        "description": (
            "Create a NEW agent from a natural-language description when no existing "
            "agent fits the goal. PI designs it and adds it to the registry; you can then "
            "delegate to it with run_agent. Returns the new agent's name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "What the agent should be/do, e.g. 'a stock portfolio tracking agent'.",
                }
            },
            "required": ["description"],
        },
    },
]

MAX_ITERATIONS = 16


class Orchestrator:
    def __init__(self, root: Path, supervisor):
        self.root = root
        self.sup = supervisor
        self.model = os.environ.get("AGENTSPACE_CONDUCTOR_MODEL", "claude-sonnet-4-6")
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    # -- tools ---------------------------------------------------------------
    def _roster(self) -> list[dict]:
        out = []
        for spec in registry.list_agents(self.root):
            out.append(
                {
                    "name": spec.name,
                    "description": spec.description or "(no description)",
                    "tools": spec.tools,
                    "running": self.sup.is_running(spec.name),
                }
            )
        return out

    def _list_agents(self) -> str:
        return json.dumps(self._roster(), indent=2)

    def _run_agent(self, agent: str, task: str, emit) -> str:
        names = {s.name for s in registry.list_agents(self.root)}
        if agent not in names:
            return f"ERROR: no such agent '{agent}'. Call list_agents first."

        if not self.sup.is_running(agent):
            emit("step", f"starting {agent}…")
            self.sup.start(agent)
            if not self.sup.is_running(agent):
                return f"ERROR: could not start agent '{agent}'."

        emit("delegate", f"{agent}  ←  {task[:110]}")
        res = self.sup.send(agent, task)
        if not res["ok"]:
            return f"ERROR: {res.get('message', 'send failed')}"
        run_id = res["data"]["run_id"]

        seen = 0
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            got = self.sup.get_run(agent, run_id)
            if not got["ok"]:
                time.sleep(0.5)
                continue
            run = got["data"]
            for ev in run["events"][seen:]:
                if ev["kind"] != "done":
                    emit("subevent", f"[{agent}] {ev['text'][:90]}")
            seen = len(run["events"])
            if run["status"] in ("done", "error"):
                out = (run.get("result") or {}).get("output_text", "")
                emit("reply", f"{agent} → {out[:120]}")
                return out or "(no output)"
            time.sleep(0.5)
        return f"ERROR: {agent} timed out."

    # -- the planning loop ---------------------------------------------------
    def run(self, goal: str, emit) -> str | None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            emit("error", "ANTHROPIC_API_KEY is not set — the conductor needs it to plan.")
            return None

        roster = json.dumps(self._roster(), indent=2)
        system = CONDUCTOR_PROMPT + "\n\nCurrent agent roster:\n" + roster
        messages = [{"role": "user", "content": goal}]

        try:
            for _ in range(MAX_ITERATIONS):
                resp = self._get_client().messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=system,
                    messages=messages,
                    tools=TOOLS,
                )
                messages.append(
                    {"role": "assistant", "content": [b.model_dump() for b in resp.content]}
                )
                for block in resp.content:
                    if getattr(block, "type", None) == "text" and block.text.strip():
                        emit("say", block.text.strip()[:200])

                if resp.stop_reason != "tool_use":
                    break

                tool_results = []
                for block in resp.content:
                    if block.type != "tool_use":
                        continue
                    args = dict(block.input)
                    if block.name == "list_agents":
                        emit("think", "discovering agents…")
                        result = self._list_agents()
                    elif block.name == "run_agent":
                        result = self._run_agent(args.get("agent", ""), args.get("task", ""), emit)
                    elif block.name == "create_agent":
                        desc = args.get("description", "")
                        emit("build", f"creating a new agent: {desc[:80]}")
                        ok, msg, _name = agent_factory.create_agent(
                            self.root, desc, progress=lambda t: emit("subevent", t)
                        )
                        result = msg
                    else:
                        result = f"ERROR: unknown tool {block.name}"
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": result}
                    )
                messages.append({"role": "user", "content": tool_results})
            else:
                emit("error", f"conductor stopped after {MAX_ITERATIONS} steps")
        except Exception as exc:  # noqa: BLE001
            emit("error", str(exc))
            return None

        # final assistant text
        final = []
        for block in messages[-1]["content"]:
            if isinstance(block, dict) and block.get("type") == "text":
                final.append(block.get("text", ""))
        return "\n".join(final).strip()
