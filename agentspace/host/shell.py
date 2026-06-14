"""The AgentSpace host — an interactive REPL control plane.

This never calls the model. It starts/stops agent processes and relays messages to
them over HTTP.

`send` is non-blocking: it starts a turn and returns immediately with a run id, so
you keep control of the prompt. A background monitor streams each agent's status
events (model turns, tool calls) as they happen and prints the final reply when the
run finishes. Use `status` to see in-flight runs and `runs <name>` for history.
"""

from __future__ import annotations

import os
import shlex
import sys
import threading
import time
from pathlib import Path

from agentspace.common import paths
from agentspace.host import agent_factory, registry
from agentspace.host.orchestrator import Orchestrator
from agentspace.host.supervisor import Supervisor

BANNER = r"""
     ||      ||
   +------------+
   |  [o]  [o]  |     A G E N T S P A C E
   |    ----    |     local agent runtime
   +------------+
     ||      ||
"""

HELP = """\
Type a goal in plain English and the conductor routes it to the right agent(s):
  > research france's world cup odds and make a cool powerpoint about it

commands:
  agents                       list agents and what each is for
  create-agent <description>   have PI build a new agent and add it to the registry
  do <goal> | ask <goal>       explicitly send a goal to the conductor
  ps | ls                      list agents and their status
  start <name>                 start an agent process
  stop <name>                  stop an agent process
  restart <name>               restart an agent process
  send <name> "<msg>" [--session <id>] [--wait]
                               send a message (async: returns a run id immediately;
                               --wait blocks until done). Status streams live.
  status                       show in-flight runs being tracked
  runs <name>                  list an agent's recent runs
  logs <name> [n]              show the last n log lines (default 40)
  sessions <name>              list an agent's sessions
  session <name> <id>          print a session's messages (turn count)
  help | ?                     show this help
  quit | exit | q              leave (offers to stop running agents)
"""

# Icons for the live status feed, by event kind.
_ICONS = {
    "start": "→",
    "model": "·",
    "say": "💬",
    "tool": "🔧",
    "tool_done": "✓",
    "progress": "  ✎",
    "system": "⚙",
    "error": "✗",
}


class Shell:
    def __init__(self, root: Path):
        self.root = root
        self.sup = Supervisor(root)
        self.orch = Orchestrator(root, self.sup)
        # run_id -> {name, seen, session_id}
        self._active: dict[str, dict] = {}
        self._active_lock = threading.Lock()
        self._stop = threading.Event()

    # -- helpers -------------------------------------------------------------
    def _agents(self):
        return registry.list_agents(self.root)

    def _print_ps(self) -> None:
        agents = self._agents()
        if not agents:
            print(f"no agents found under {paths.agents_dir(self.root)}")
            return
        print(f"{'NAME':<14}{'STATUS':<10}{'PORT':<7}{'PID':<8}{'MODEL':<22}TOOLS")
        for spec in agents:
            st = self.sup.status(spec.name)
            status = "running" if st["running"] else "stopped"
            port = str(st["port"] or "-")
            pid = str(st["pid"] or "-")
            tools = ",".join(spec.tools) or "-"
            print(f"{spec.name:<14}{status:<10}{port:<7}{pid:<8}{spec.model:<22}{tools}")

    def _print_final(self, name: str, data: dict) -> None:
        print(f"\n{name}> {data.get('output_text', '')}\n")
        u = data.get("usage", {})
        print(
            f"  [session {data.get('session_id', '?')} · {u.get('iterations', '?')} turns · "
            f"{u.get('tool_calls', 0)} tool calls · "
            f"{u.get('input_tokens', 0)}in/{u.get('output_tokens', 0)}out tokens]"
        )

    # -- live status monitor -------------------------------------------------
    def _monitor(self) -> None:
        while not self._stop.is_set():
            with self._active_lock:
                items = list(self._active.items())
            for run_id, info in items:
                res = self.sup.get_run(info["name"], run_id)
                if not res["ok"]:
                    continue
                run = res["data"]
                events = run.get("events", [])
                for ev in events[info["seen"]:]:
                    if ev["kind"] == "done":
                        continue
                    icon = _ICONS.get(ev["kind"], "·")
                    print(f"  [{info['name']}·{run_id}] {icon} {ev['text']}")
                info["seen"] = len(events)
                if run["status"] in ("done", "error"):
                    if run.get("result"):
                        self._print_final(info["name"], run["result"])
                    with self._active_lock:
                        self._active.pop(run_id, None)
            self._stop.wait(0.7)

    def _track(self, name: str, run_id: str, session_id: str) -> None:
        with self._active_lock:
            self._active[run_id] = {"name": name, "seen": 0, "session_id": session_id}

    # -- commands ------------------------------------------------------------
    def cmd_start(self, args):
        if not args:
            print("usage: start <name>")
            return
        print(self.sup.start(args[0])["message"])

    def cmd_stop(self, args):
        if not args:
            print("usage: stop <name>")
            return
        print(self.sup.stop(args[0])["message"])

    def cmd_restart(self, args):
        if not args:
            print("usage: restart <name>")
            return
        print(self.sup.restart(args[0])["message"])

    def cmd_send(self, args):
        if len(args) < 2:
            print('usage: send <name> "<message>" [--session <id>] [--wait]')
            return
        name = args[0]
        rest = list(args[1:])
        wait = False
        if "--wait" in rest:
            wait = True
            rest.remove("--wait")
        session_id = None
        if "--session" in rest:
            i = rest.index("--session")
            try:
                session_id = rest[i + 1]
            except IndexError:
                print("--session requires an id")
                return
            rest = rest[:i] + rest[i + 2 :]
        message = " ".join(rest)

        result = self.sup.send(name, message, session_id, wait=wait)
        if not result["ok"]:
            print(result["message"])
            return
        data = result["data"]
        if wait:
            self._print_final(name, data.get("result", data))
            return
        run_id = data["run_id"]
        self._track(name, run_id, data["session_id"])
        print(f"→ {name} run {run_id} started (session {data['session_id']}). status streams below.")

    def cmd_status(self, args):
        with self._active_lock:
            items = list(self._active.items())
        if not items:
            print("no in-flight runs.")
            return
        print(f"{'RUN':<16}{'AGENT':<14}{'SESSION':<14}EVENTS")
        for run_id, info in items:
            print(f"{run_id:<16}{info['name']:<14}{info['session_id']:<14}{info['seen']}")

    def cmd_agents(self, args):
        agents = self._agents()
        if not agents:
            print("no agents found.")
            return
        for spec in agents:
            print(f"{spec.name:<14}{spec.description or '(no description)'}")

    def cmd_create_agent(self, description: str):
        """Have PI design a new agent from a description (runs in the background)."""
        description = description.strip()
        if not description:
            print('usage: create-agent <description>   e.g. create-agent a stock portfolio tracking agent')
            return

        def work():
            print(f"🏗  building an agent for: {description}")
            ok, message, name = agent_factory.create_agent(
                self.root, description, progress=lambda t: print(f"  ✎ {t}")
            )
            print(f"\n{message}\n")

        threading.Thread(target=work, daemon=True).start()

    def cmd_orchestrate(self, goal: str):
        """Hand a natural-language goal to the conductor (runs in the background)."""
        goal = goal.strip()
        if not goal:
            return
        icons = {
            "think": "🧭", "say": "🧭", "step": "  …", "delegate": "  →",
            "build": "  🏗", "subevent": "      ·", "reply": "  ✓", "error": "  ✗",
        }

        def work():
            def emit(kind, text):
                print(f"{icons.get(kind, '  ·')} {text}")

            print(f"🧭 conductor: {goal}")
            final = self.orch.run(goal, emit)
            if final:
                print(f"\nconductor> {final}\n")

        threading.Thread(target=work, daemon=True).start()

    def cmd_runs(self, args):
        if not args:
            print("usage: runs <name>")
            return
        res = self.sup.list_runs(args[0])
        if not res["ok"]:
            print(res["message"])
            return
        runs = res["data"]["runs"]
        if not runs:
            print("(no runs yet)")
            return
        print(f"{'RUN':<16}{'STATUS':<10}{'EV':<5}PROMPT")
        for r in runs:
            print(f"{r['run_id']:<16}{r['status']:<10}{r['events']:<5}{r['prompt']}")

    def cmd_logs(self, args):
        if not args:
            print("usage: logs <name> [n]")
            return
        n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 40
        print(self.sup.tail_log(args[0], n))

    def cmd_sessions(self, args):
        if not args:
            print("usage: sessions <name>")
            return
        result = self.sup.get_json(args[0], "/sessions")
        if not result["ok"]:
            print(result["message"])
            return
        ids = result["data"]["sessions"]
        print("\n".join(ids) if ids else "(no sessions yet)")

    def cmd_session(self, args):
        if len(args) < 2:
            print("usage: session <name> <id>")
            return
        result = self.sup.get_json(args[0], f"/sessions/{args[1]}")
        if not result["ok"]:
            print(result["message"])
            return
        msgs = result["data"]["messages"]
        print(f"session {args[1]}: {len(msgs)} messages")
        for m in msgs:
            role = m["role"]
            content = m["content"]
            if isinstance(content, str):
                preview = content
            else:
                kinds = [b.get("type", "?") for b in content if isinstance(b, dict)]
                preview = "+".join(kinds)
            print(f"  {role:<10} {str(preview)[:90]}")

    # -- loop ----------------------------------------------------------------
    COMMANDS = {
        "quit", "exit", "q", "help", "?", "ps", "ls", "start", "stop", "restart",
        "send", "status", "runs", "logs", "sessions", "session", "agents", "do", "ask",
        "create-agent",
    }

    def dispatch(self, line: str) -> bool:
        """Run one command. Returns False to exit. Free text → the conductor."""
        line = line.strip()
        if not line:
            return True

        first = line.split()[0]
        # Anything that isn't a known command is a natural-language goal.
        if first not in self.COMMANDS:
            self.cmd_orchestrate(line)
            return True
        if first in ("do", "ask"):
            self.cmd_orchestrate(line[len(first):])
            return True
        if first == "create-agent":
            self.cmd_create_agent(line[len("create-agent"):])
            return True

        try:
            parts = shlex.split(line)
        except ValueError as exc:
            print(f"parse error: {exc}")
            return True
        cmd, args = parts[0], parts[1:]

        if cmd in ("quit", "exit", "q"):
            return self._quit()
        handlers = {
            "help": lambda a: print(HELP),
            "?": lambda a: print(HELP),
            "agents": self.cmd_agents,
            "ps": lambda a: self._print_ps(),
            "ls": lambda a: self._print_ps(),
            "start": self.cmd_start,
            "stop": self.cmd_stop,
            "restart": self.cmd_restart,
            "send": self.cmd_send,
            "status": self.cmd_status,
            "runs": self.cmd_runs,
            "logs": self.cmd_logs,
            "sessions": self.cmd_sessions,
            "session": self.cmd_session,
        }
        handlers[cmd](args)
        return True

    def _quit(self) -> bool:
        self._stop.set()
        running = self.sup.running_agents()
        if running:
            ans = input(f"stop running agents ({', '.join(running)})? [y/N] ").strip().lower()
            if ans == "y":
                for name in running:
                    print(self.sup.stop(name)["message"])
        print("bye.")
        return False

    def run(self) -> None:
        print(BANNER)
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("⚠️  ANTHROPIC_API_KEY is not set — agents will start but `send` will error.")
            print("    export ANTHROPIC_API_KEY=sk-ant-... then restart the host.\n")
        print(f"root: {self.root}")
        print("type a goal in plain English (the conductor routes it), or `help` for commands.\n")
        self._print_ps()
        print()

        monitor = threading.Thread(target=self._monitor, daemon=True)
        monitor.start()

        prompt_fn = _make_prompt()
        while True:
            try:
                line = prompt_fn("agentspace> ")
            except (EOFError, KeyboardInterrupt):
                print()
                self._quit()
                break
            if not self.dispatch(line):
                break
        self._stop.set()


def _make_prompt():
    """Use prompt_toolkit (with patch_stdout so background status prints cleanly
    above the prompt) if available/interactive, else plain input()."""
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import InMemoryHistory
        from prompt_toolkit.patch_stdout import patch_stdout

        session = PromptSession(history=InMemoryHistory())

        def fn(msg):
            with patch_stdout():
                return session.prompt(msg)

        return fn
    except Exception:  # noqa: BLE001
        return input


def main() -> None:
    root = paths.repo_root()
    if not paths.agents_dir(root).is_dir():
        print(f"error: no agents/ directory found from {Path.cwd()}", file=sys.stderr)
        sys.exit(1)
    Shell(root).run()


if __name__ == "__main__":
    main()
