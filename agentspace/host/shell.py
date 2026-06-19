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
import shutil
import sys
import threading
import time
from pathlib import Path

from agentspace.agent.mcp_client import load_catalog
from agentspace.agent.tools import registry as tool_registry
from agentspace.common import pricing
from agentspace.agent.tools.skills import skill_description
from agentspace.common import paths
from agentspace.host import agent_factory, deploy, registry
from agentspace.host import settings as settings_mod
from agentspace.host.orchestrator import Orchestrator
from agentspace.common.schedule import parse_schedule
from agentspace.host.scheduler import Ticker
from agentspace.host.supervisor import Supervisor
from agentspace.host.telegram_bridge import TelegramBridge

BANNER = r"""
     ||      ||
   +------------+
   |  [o]  [o]  |     A G E N T S P A C E
   |    ----    |     local agent runtime
   +------------+
     ||      ||
"""

HELP = """\
Just type a goal in plain English — the conductor routes it to the right agent(s):
  > research france's world cup odds and make a cool powerpoint about it

Commands start with "/" (anything without a slash goes to the conductor):
  /list                         plain-English overview of every agent, tool & skill
  /settings [...]               show/change models live (agents, conductor, pi, key)
  /setup                        re-run the first-time setup flow
  /mcp                          list MCP servers and live connection status
  /deploy <agent>               deploy an agent to Render (cloud); reachable like a local one
  /undeploy <agent>             remove a deployed agent from Render
  /deploys                      list deployed (remote) agents and their URLs
  /agents                       list agents and what each is for
  /create-agent <description>   have PI build a new agent and add it to the registry
  /clean [output|tools|sessions|all]
                                move agent-produced files to trash (default: output/)
  /trash [list|restore [batch]|empty]
                                inspect / undo / purge what /clean moved aside
  /ps | /ls                     agent status table (running/stopped, port, pid)
  /start <name>                 start an agent process
  /stop <name>                  stop an agent process
  /restart <name>               restart an agent process
  /send <name> "<msg>" [--session <id>] [--wait]
                                send a message (async: returns a run id immediately;
                                --wait blocks until done). Status streams live.
  /status                       show in-flight runs being tracked
  /stream [on|off]              toggle inline event streaming (off = clean REPL; use the monitor)
  /gc                           sweep orphan agent processes left by a previous host session
  /runs <name>                  list an agent's recent runs
  /logs <name> [n]              show the last n log lines (default 40)
  /sessions <name>              list an agent's sessions
  /session <name> <id>          print a session's messages (turn count)
  /schedule [list|cancel <id>]  timed/recurring runs (or just say "check X every hour today")
  /help | /quit                 help / leave (quit offers to stop running agents)
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
        self.settings = settings_mod.load(root)
        self._apply_settings()
        # run_id -> {name, seen, session_id}
        self._active: dict[str, dict] = {}
        self._active_lock = threading.Lock()
        self._stop = threading.Event()
        self._stream = True  # inline interim event streaming in the REPL
        self.ticker = Ticker(root, fire=self._fire_scheduled)
        self.telegram = TelegramBridge(self.orch)

    def _apply_settings(self) -> None:
        """Make the loaded settings take effect (conductor model + PI env)."""
        self.orch.model = self.settings.conductor_model
        os.environ["AGENTSPACE_PI_PROVIDER"] = self.settings.pi_provider
        if self.settings.pi_model:
            os.environ["AGENTSPACE_PI_MODEL"] = self.settings.pi_model
        else:
            os.environ.pop("AGENTSPACE_PI_MODEL", None)

    # -- helpers -------------------------------------------------------------
    def _agents(self):
        return registry.list_agents(self.root)

    def _print_ps(self) -> None:
        agents = self._agents()
        if not agents:
            print(f"no agents found under {paths.agents_dir(self.root)}")
            return
        print(f"{'NAME':<18}{'STATUS':<10}{'LOCATION':<26}{'MODEL':<22}TOOLS")
        for spec in agents:
            st = self.sup.status(spec.name)
            status = "running" if st["running"] else "stopped"
            if st["location"] == "remote":
                location = st["url"].replace("https://", "").replace("http://", "")
            else:
                location = f"local :{st['port']}" if st["port"] else "local"
            tools = ",".join(spec.tools) or "-"
            print(f"{spec.name:<18}{status:<10}{location:<26}{spec.model:<22}{tools}")

    def _print_final(self, name: str, data: dict) -> None:
        print(f"\n{name}> {data.get('output_text', '')}\n")
        u = data.get("usage", {})
        cost = pricing.estimate_cost(
            data.get("model", ""), u.get("input_tokens", 0), u.get("output_tokens", 0)
        )
        print(
            f"  [session {data.get('session_id', '?')} · {u.get('iterations', '?')} turns · "
            f"{u.get('tool_calls', 0)} tool calls · "
            f"{u.get('input_tokens', 0)}in/{u.get('output_tokens', 0)}out tok · "
            f"~{pricing.fmt(cost)} ({data.get('model', '?')})]"
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
                if self._stream:
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

    def cmd_gc(self, args):
        reaped = self.sup.reap_orphans()
        print(f"swept {len(reaped)} orphan agent process(es)." if reaped else "no orphan processes found.")

    def cmd_stream(self, args):
        if args and args[0].lower() in ("on", "off"):
            self._stream = args[0].lower() == "on"
        else:
            self._stream = not self._stream
        state = "on" if self._stream else "off"
        extra = "" if self._stream else " — use `agentspace-monitor` for per-agent panes"
        print(f"inline streaming: {state}{extra}")

    def cmd_status(self, args):
        with self._active_lock:
            items = list(self._active.items())
        if not items:
            print("no in-flight runs.")
            return
        print(f"{'RUN':<16}{'AGENT':<14}{'SESSION':<14}EVENTS")
        for run_id, info in items:
            print(f"{run_id:<16}{info['name']:<14}{info['session_id']:<14}{info['seen']}")

    @staticmethod
    def _short(text: str, n: int = 100) -> str:
        text = " ".join((text or "").split())
        head = text.split(". ")[0]
        return (head if len(head) <= n else text[:n]).rstrip(".") + ("…" if len(text) > n else "")

    # Friendly blurbs for tools whose schema text is verbose or who have no handler.
    _TOOL_BLURBS = {
        "web_search": "search the web for current information (runs on Anthropic's side)",
        "sh": "run shell commands on the host machine",
        "load_skill": "pull in a skill's full instructions on demand",
        "write_tool": "author a brand-new tool on the fly (PI writes it, then it's usable)",
    }

    def cmd_list(self, args=None):
        agents = self._agents()
        print(f"\nYou have {len(agents)} agent(s):")
        for spec in agents:
            state = "running" if self.sup.is_running(spec.name) else "stopped"
            selfext = "  ·  can write its own tools" if spec.can_author_tools else ""
            print(f"  • {spec.name}  ({state}) — {spec.description or 'no description'}")
            print(f"      tools: {', '.join(spec.tools) or 'none'}{selfext}")

        discovered = tool_registry.discover()
        print("\nTools agents can use:")
        print(f"  • web_search — {self._TOOL_BLURBS['web_search']}")
        for name in sorted(discovered):
            blurb = self._TOOL_BLURBS.get(name) or self._short(discovered[name].schema.get("description", ""))
            tag = "  [PI-authored]" if discovered[name].generated else ""
            print(f"  • {name} — {blurb}{tag}")

        skills_dir = paths.skills_dir(self.root)
        skills = sorted(p.name for p in skills_dir.iterdir() if (p / "SKILL.md").is_file()) \
            if skills_dir.is_dir() else []
        if skills:
            print("\nSkills (playbooks loaded on demand):")
            for s in skills:
                print(f"  • {s} — {self._short(skill_description(skills_dir, s))}")

        catalog = load_catalog(self.root)
        if catalog:
            print("\nMCP servers (extra tools via Model Context Protocol):")
            for name, cfg in catalog.items():
                transport = "remote http" if cfg.get("url") else "stdio"
                disabled = "" if cfg.get("enabled", True) else "  (disabled)"
                users = [s.name for s in self._agents() if name in (s.mcp_servers or [])]
                print(f"  • {name} [{transport}]{disabled} — used by: {', '.join(users) or 'no agent yet'}")

        print("\nThe system extends itself: agents author new tools with write_tool, "
              "and you can spin up new agents with /create-agent.\n")

    # -- settings & setup ----------------------------------------------------
    def _set_agent_model(self, name: str, model: str) -> str:
        cfg = registry.config_path(self.root, name)
        if not cfg.is_file():
            return f"no such agent: {name}"
        lines = cfg.read_text().splitlines()
        for i, line in enumerate(lines):
            if line.lstrip().startswith("model:"):
                indent = line[: len(line) - len(line.lstrip())]
                lines[i] = f"{indent}model: {model}"
                break
        else:
            lines.insert(1, f"model: {model}")
        cfg.write_text("\n".join(lines) + "\n")
        msg = f"{name} → {model}"
        if self.sup.is_running(name):
            self.sup.restart(name)
            msg += " (restarted)"
        return msg

    def _show_settings(self) -> None:
        key = "set" if os.environ.get("ANTHROPIC_API_KEY") else "NOT set"
        pim = self.settings.pi_model or "(PI default)"
        print(f"\nAPI key:           {key}")
        print(f"conductor model:   {self.settings.conductor_model}")
        print(f"pi provider/model: {self.settings.pi_provider} / {pim}")
        print("\nagent models:")
        for spec in self._agents():
            state = "running" if self.sup.is_running(spec.name) else "stopped"
            print(f"  {spec.name:<18}{spec.model:<22}({state})")
        print("\nchange live: /settings model <agent|all> <model> · "
              "/settings conductor <model> · /settings pi <model>")
        print("models: opus | sonnet | haiku  (or a full id)\n")

    def cmd_settings(self, args):
        if not args:
            self._show_settings()
            return
        sub = args[0].lower()
        if sub == "model":
            if len(args) < 3:
                print("usage: /settings model <agent|all> <model>")
                return
            model = settings_mod.resolve_model(args[2])
            targets = [s.name for s in self._agents()] if args[1] == "all" else [args[1]]
            for name in targets:
                print("  " + self._set_agent_model(name, model))
        elif sub == "conductor":
            if len(args) < 2:
                print("usage: /settings conductor <model>")
                return
            self.settings.conductor_model = settings_mod.resolve_model(args[1])
            settings_mod.save(self.root, self.settings)
            self._apply_settings()
            print(f"conductor model → {self.settings.conductor_model}")
        elif sub == "pi":
            if len(args) < 2:
                print("usage: /settings pi <model>")
                return
            self.settings.pi_model = settings_mod.resolve_model(args[1])
            settings_mod.save(self.root, self.settings)
            self._apply_settings()
            print(f"pi model → {self.settings.pi_model}")
        elif sub == "key":
            if len(args) < 2:
                print("usage: /settings key <api-key>")
                return
            os.environ["ANTHROPIC_API_KEY"] = args[1]
            print("ANTHROPIC_API_KEY set for this session (not persisted — add to your shell profile to keep it).")
        else:
            print("usage: /settings [model <agent|all> <model> | conductor <model> | pi <model> | key <api-key>]")

    def cmd_setup(self, args=None):
        self.run_setup(initial=False)

    def run_setup(self, initial: bool = False) -> None:
        print("\n— AgentSpace setup —")
        if initial:
            print("Looks like your first run! Quick setup (re-run anytime with /setup).\n")

        # 1) API key
        if os.environ.get("ANTHROPIC_API_KEY"):
            print("✓ ANTHROPIC_API_KEY detected.")
        else:
            print("Agents call the Anthropic Messages API, so they need an API key.")
            v = input("  paste ANTHROPIC_API_KEY now (or Enter to skip): ").strip()
            if v:
                os.environ["ANTHROPIC_API_KEY"] = v
                print("  ✓ set for this session. To keep it, add it to your ~/.zprofile.")
            else:
                print("  skipped — the conductor and /send will error until it's set.")

        # 2) default model
        print("\nPick a default model:")
        print("  1) sonnet  (claude-sonnet-4-6) — balanced [default]")
        print("  2) opus    (claude-opus-4-8)   — most capable")
        print("  3) haiku   (claude-haiku-4-5)  — fastest / cheapest")
        print("  4) keep current")
        pick = {"1": "sonnet", "2": "opus", "3": "haiku"}.get(input("  > ").strip())
        if pick:
            model = settings_mod.resolve_model(pick)
            self.settings.conductor_model = model
            if input(f"  apply {model} to ALL agents too? [y/N] ").strip().lower() == "y":
                for spec in self._agents():
                    self._set_agent_model(spec.name, model)
                print(f"  ✓ all agents → {model}")
            print(f"  ✓ conductor → {model}")

        # 3) optional capabilities
        def mark(ok, hint):
            return "✓ installed" if ok else f"✗ missing — {hint}"

        print("\nOptional capabilities:")
        print(f"  pi  (write_tool / create-agent): {mark(shutil.which('pi'), 'npm i -g @mariozechner/pi-coding-agent')}")
        print(f"  npx (filesystem/github MCP):     {mark(shutil.which('npx'), 'install Node.js')}")
        print(f"  uvx (fetch/git MCP):             {mark(shutil.which('uvx'), 'install uv')}")

        settings_mod.save(self.root, self.settings)
        self._apply_settings()
        print("\nsetup saved. type /help for commands, or just say what you want.\n")

    def cmd_mcp(self, args):
        catalog = load_catalog(self.root)
        if not catalog:
            print("no MCP servers configured (see mcp/servers.yaml).")
            return
        print("MCP servers (from mcp/servers.yaml):")
        for name, cfg in catalog.items():
            transport = f"remote {cfg['url']}" if cfg.get("url") else f"stdio: {cfg.get('command','?')}"
            disabled = "" if cfg.get("enabled", True) else "  (disabled)"
            print(f"  • {name} — {transport}{disabled}")
        print("\nLive connections (running agents):")
        any_live = False
        for spec in self._agents():
            if spec.mcp_servers and self.sup.is_running(spec.name):
                res = self.sup.get_json(spec.name, "/mcp")
                if res["ok"]:
                    any_live = True
                    d = res["data"]
                    conn = ", ".join(f"{k}={'✓' if v else '✗'}" for k, v in d["servers"].items())
                    print(f"  • {spec.name}: {conn}  ({len(d['tools'])} mcp tools)")
        if not any_live:
            print("  (no running agents use MCP — `/start files` to try the filesystem server)")

    def cmd_agents(self, args):
        agents = self._agents()
        if not agents:
            print("no agents found.")
            return
        for spec in agents:
            print(f"{spec.name:<14}{spec.description or '(no description)'}")

    def _trash_root(self) -> Path:
        return paths.runtime_dir(self.root) / ".trash"

    def _new_trash_batch(self) -> Path:
        ts = time.strftime("%Y%m%d-%H%M%S")
        base = self._trash_root() / ts
        d, i = base, 2
        while d.exists():
            d = self._trash_root() / f"{ts}-{i}"
            i += 1
        return d

    def _clean_output(self, trash: Path) -> tuple[str, int]:
        d = paths.output_dir(self.root)
        files = [p for p in d.rglob("*") if p.is_file()] if d.exists() else []
        if not files:
            return "output/: nothing to clean", 0
        dest = trash / "output"
        dest.mkdir(parents=True, exist_ok=True)
        for p in d.iterdir():
            shutil.move(str(p), str(dest / p.name))
        return f"output/: moved {len(files)} file(s) to trash", len(files)

    def _clean_tools(self, trash: Path) -> tuple[str, int]:
        d = paths.generated_tools_dir()
        tools = [p for p in d.glob("*.py") if p.name != "__init__.py"]
        pycache = d / "__pycache__"
        if pycache.exists():
            shutil.rmtree(pycache)
        if not tools:
            return "generated tools: nothing to clean", 0
        dest = trash / "tools"
        dest.mkdir(parents=True, exist_ok=True)
        for p in tools:
            shutil.move(str(p), str(dest / p.name))
        return f"generated tools: moved {len(tools)} to trash", len(tools)

    def _clean_sessions(self, trash: Path) -> tuple[str, int]:
        moved = 0
        for spec in self._agents():
            sdir = paths.agent_runtime_dir(self.root, spec.name) / "sessions"
            for p in sdir.glob("*.json") if sdir.exists() else []:
                dest = trash / "sessions" / spec.name
                dest.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(dest / p.name))
                moved += 1
        return f"sessions: moved {moved} to trash" if moved else "sessions: nothing to clean", moved

    def cmd_clean(self, args):
        target = (args[0].lower() if args else "output")
        if target not in ("output", "tools", "sessions", "all"):
            print("usage: /clean [output|tools|sessions|all]   (default: output)")
            return
        trash = self._new_trash_batch()
        trash.mkdir(parents=True, exist_ok=True)
        total = 0
        if target in ("output", "all"):
            msg, n = self._clean_output(trash); total += n; print(msg)
        if target in ("tools", "all"):
            msg, n = self._clean_tools(trash); total += n; print(msg)
        if target in ("sessions", "all"):
            msg, n = self._clean_sessions(trash); total += n; print(msg)
        if total == 0:
            shutil.rmtree(trash, ignore_errors=True)
        else:
            print(f"→ moved to trash batch '{trash.name}'. "
                  f"restore with /trash restore, or purge with /trash empty.")

    def cmd_trash(self, args):
        sub = (args[0].lower() if args else "list")
        troot = self._trash_root()
        batches = sorted(p for p in troot.iterdir() if p.is_dir()) if troot.exists() else []

        if sub == "list":
            if not batches:
                print("trash is empty.")
                return
            for b in batches:
                n = sum(1 for p in b.rglob("*") if p.is_file())
                print(f"  {b.name}  ({n} file(s))")
            print("restore latest with /trash restore [batch]; purge all with /trash empty")
        elif sub == "empty":
            if troot.exists():
                shutil.rmtree(troot)
            print("trash emptied.")
        elif sub == "restore":
            if not batches:
                print("trash is empty — nothing to restore.")
                return
            name = args[1] if len(args) > 1 else batches[-1].name
            batch = troot / name
            if not batch.is_dir():
                print(f"no such trash batch: {name}")
                return
            print(self._restore_batch(batch))
        else:
            print("usage: /trash [list|restore [batch]|empty]")

    def _restore_batch(self, batch: Path) -> str:
        restored = 0

        def move_back(src: Path, dest: Path) -> int:
            if not src.exists():
                return 0
            dest.mkdir(parents=True, exist_ok=True)
            count = 0
            for p in src.iterdir():
                shutil.move(str(p), str(dest / p.name))
                count += 1
            return count

        restored += move_back(batch / "output", paths.output_dir(self.root))
        restored += move_back(batch / "tools", paths.generated_tools_dir())
        sess = batch / "sessions"
        if sess.exists():
            for agent_dir in sess.iterdir():
                restored += move_back(
                    agent_dir, paths.agent_runtime_dir(self.root, agent_dir.name) / "sessions"
                )
        shutil.rmtree(batch, ignore_errors=True)
        return f"restored {restored} file(s) from '{batch.name}'."

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

    def cmd_deploy(self, args):
        if not args:
            print("usage: /deploy <agent>   — deploy an agent to Render (needs RENDER_API_KEY + AGENTSPACE_TOKEN)")
            return
        name = args[0]

        def work():
            print(f"☁  deploying {name} to Render…")
            ok, msg, _info = deploy.create_or_deploy(self.root, name, progress=lambda t: print(f"  · {t}"))
            print(f"\n{msg}\n")
            if ok:
                print(f"  now reachable like any agent: /send {name} \"…\"\n")

        threading.Thread(target=work, daemon=True).start()

    def cmd_undeploy(self, args):
        if not args:
            print("usage: /undeploy <agent>")
            return
        ok, msg = deploy.delete(self.root, args[0], progress=lambda t: print(f"  · {t}"))
        print(msg)

    def cmd_deploys(self, args):
        from agentspace.host import remotes
        deployed = remotes.load(self.root)
        if not deployed:
            print("no agents deployed. /deploy <agent> to host one on Render.")
            return
        print(f"{'AGENT':<16}{'STATUS':<10}URL")
        for name, info in deployed.items():
            state = "reachable" if self.sup.is_running(name) else "unreachable"
            print(f"{name:<16}{state:<10}{info['url']}")

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
                print(f"\nconductor> {final}")
                print(f"  [≈ {pricing.fmt(self.orch.last_cost)} for this goal (conductor + delegations)]\n")

        threading.Thread(target=work, daemon=True).start()

    def _fire_scheduled(self, job):
        """A scheduled job came due: run its goal through the conductor."""
        def emit(kind, text):
            if kind in ("reply", "say", "error", "delegate"):
                print(f"  ⏰ {text}")
        print(f"\n⏰ scheduled {job.id}: {job.goal}")
        final = self.orch.run(job.goal, emit)
        if final:
            print(f"⏰ {job.id}> {final}\n")

    def cmd_schedule(self, args):
        """List / cancel / add scheduled jobs. Creating via plain English (handled by
        the scheduler agent through the conductor) is the usual path; this is the
        manual shortcut."""
        sub = args[0].lower() if args else "list"
        store = self.ticker.store
        if sub in ("list", "ls"):
            jobs = store.list()
            if not jobs:
                print("no scheduled jobs. try: check google stock at 3pm")
                return
            print(f"{len(jobs)} scheduled job(s):")
            for j in jobs:
                print(f"  {j.describe()}")
        elif sub in ("cancel", "rm", "remove"):
            if len(args) < 2:
                print("usage: /schedule cancel <id|all>")
                return
            jid = args[1]
            if jid.lower() == "all":
                print(f"cancelled {store.clear()} job(s).")
            else:
                print(f"cancelled {jid}." if store.remove(jid) else f"no job {jid!r}.")
        elif sub in ("pause", "resume"):
            if len(args) < 2:
                print(f"usage: /schedule {sub} <id>")
                return
            ok = store.set_paused(args[1], sub == "pause")
            print(f"{sub}d {args[1]}." if ok else f"no job {args[1]!r}.")
        elif sub == "add":
            # /schedule add <when> :: <goal>
            rest = " ".join(args[1:])
            if "::" not in rest:
                print('usage: /schedule add <when> :: <goal>')
                return
            when, goal = (p.strip() for p in rest.split("::", 1))
            parsed = parse_schedule(when)
            if parsed is None:
                print(f"couldn't parse a time from {when!r}.")
                return
            sched, _ = parsed
            job = store.add(goal, sched)
            print(f"scheduled {job.id}: {goal!r} — {sched.label}.")
        else:
            print("usage: /schedule [list | add <when> :: <goal> | "
                  "cancel <id|all> | pause <id> | resume <id>]")

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
    def dispatch(self, line: str) -> bool:
        """Run one line. Commands start with '/'; everything else is a natural-language
        goal handed to the conductor. Returns False to exit."""
        line = line.strip()
        if not line:
            return True

        # Bare safety words work without a slash (so a habitual `quit` doesn't hit the LLM).
        if line.lower() in ("quit", "exit", "q"):
            return self._quit()
        if line.lower() in ("help", "?"):
            print(HELP)
            return True

        # No slash → talk to the conductor.
        if not line.startswith("/"):
            self.cmd_orchestrate(line)
            return True

        body = line[1:].strip()
        if not body:
            return True
        first = body.split()[0].lower()

        if first in ("quit", "exit", "q"):
            return self._quit()
        if first in ("help", "?"):
            print(HELP)
            return True
        # Commands whose argument is free text (keep it unparsed).
        if first == "create-agent":
            self.cmd_create_agent(body[len("create-agent"):])
            return True
        if first in ("do", "ask"):
            self.cmd_orchestrate(body[len(first):])
            return True

        try:
            parts = shlex.split(body)
        except ValueError as exc:
            print(f"parse error: {exc}")
            return True
        cmd, args = parts[0].lower(), parts[1:]
        handlers = {
            "list": self.cmd_list,
            "settings": self.cmd_settings,
            "setup": self.cmd_setup,
            "mcp": self.cmd_mcp,
            "deploy": self.cmd_deploy,
            "undeploy": self.cmd_undeploy,
            "deploys": self.cmd_deploys,
            "clean": self.cmd_clean,
            "trash": self.cmd_trash,
            "agents": self.cmd_agents,
            "ps": lambda a: self._print_ps(),
            "ls": lambda a: self._print_ps(),
            "start": self.cmd_start,
            "stop": self.cmd_stop,
            "restart": self.cmd_restart,
            "send": self.cmd_send,
            "status": self.cmd_status,
            "stream": self.cmd_stream,
            "gc": self.cmd_gc,
            "runs": self.cmd_runs,
            "logs": self.cmd_logs,
            "sessions": self.cmd_sessions,
            "session": self.cmd_session,
            "schedule": self.cmd_schedule,
            "sched": self.cmd_schedule,
        }
        handler = handlers.get(cmd)
        if handler is None:
            print(f"unknown command: /{cmd} (try /help)")
        else:
            handler(args)
        return True

    def _quit(self) -> bool:
        self._stop.set()
        self.ticker.stop()
        self.telegram.stop()
        running = self.sup.running_agents()
        if running:
            try:
                ans = input(f"stop running agents ({', '.join(running)})? [y/N] ").strip().lower()
            except EOFError:
                ans = "n"
            if ans == "y":
                for name in running:
                    print(self.sup.stop(name)["message"])
        print("bye.")
        return False

    def run(self) -> None:
        print(BANNER)
        reaped = self.sup.reap_orphans()
        if reaped:
            print(f"swept {len(reaped)} orphan agent process(es) from a previous session.")
        if settings_mod.is_first_run(self.root):
            self.run_setup(initial=True)
        elif not os.environ.get("ANTHROPIC_API_KEY"):
            print("⚠️  ANTHROPIC_API_KEY is not set — the conductor and `/send` will error.")
            print("    set it with `/settings key <key>` or re-run `/setup`.\n")
        print(f"root: {self.root}")
        print("type a goal in plain English (the conductor routes it). commands start with / — try /list or /help.\n")
        self._print_ps()
        print()

        monitor = threading.Thread(target=self._monitor, daemon=True)
        monitor.start()
        self.ticker.start()
        pending = self.ticker.store.list()
        if pending:
            print(f"⏰ {len(pending)} scheduled job(s) loaded — /schedule to view.\n")
        self.telegram.start()

        prompt_fn = self._make_prompt()
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

    def _make_prompt(self):
        """Pin a clean input area at the bottom of the terminal: a styled prompt with a
        status toolbar, and `patch_stdout` so all streaming output scrolls ABOVE it
        instead of mixing with what you're typing. Falls back to input() if prompt_toolkit
        isn't available / not a TTY."""
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
            from prompt_toolkit.formatted_text import HTML
            from prompt_toolkit.history import FileHistory
            from prompt_toolkit.patch_stdout import patch_stdout
            from prompt_toolkit.styles import Style

            style = Style.from_dict({
                "prompt": "ansigreen bold",
                "bottom-toolbar": "bg:#10302a #9bd9b0",
            })

            def toolbar():
                with self._active_lock:
                    n = len(self._active)
                busy = f" · {n} in-flight" if n else ""
                key = "" if os.environ.get("ANTHROPIC_API_KEY") else " · ⚠ no API key"
                return HTML(
                    f" AgentSpace   plain text → conductor   ·   /help  ·  /list  ·  /quit{busy}{key} "
                )

            # Persist input history across sessions (↑ recalls past commands & goals).
            hist_path = paths.runtime_dir(self.root) / "history"
            hist_path.parent.mkdir(parents=True, exist_ok=True)

            session = PromptSession(
                history=FileHistory(str(hist_path)),
                auto_suggest=AutoSuggestFromHistory(),
                style=style,
                bottom_toolbar=toolbar,
                refresh_interval=0.5,
            )

            def fn(_msg=None):
                with patch_stdout():
                    return session.prompt(HTML("<prompt>agentspace ❯</prompt> "))

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
