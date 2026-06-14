"""A live dashboard for AgentSpace — one dedicated pane per running agent.

Run it in a second terminal alongside the host:

    uv run agentspace-monitor

Each running agent gets its own boxed area that streams ONLY its events (model turns,
tool calls, PI steps, replies), so multiple agents never interleave. It polls every
agent's `/runs` endpoint; read-only. Press `q` (or Ctrl-C) to quit.

Falls back to a flat, timestamped feed if prompt_toolkit isn't available or stdout isn't
a TTY.
"""

from __future__ import annotations

import shutil
import sys
import threading
import time
from collections import deque

from agentspace.common import paths
from agentspace.host import registry
from agentspace.host.supervisor import Supervisor

_ICONS = {
    "start": "→", "model": "·", "say": "💬", "tool": "🔧", "tool_done": "✓",
    "progress": "✎", "system": "⚙", "error": "✗", "done": "■",
}
_STYLE = {
    "tool": "fg:ansiyellow", "tool_done": "fg:ansigreen", "say": "fg:ansicyan",
    "progress": "fg:ansibrightblack", "system": "fg:ansibrightblack",
    "error": "fg:ansired", "done": "fg:ansigreen", "reply": "fg:ansigreen",
}
PANE_MAX = 200


def _line_for(ev: dict) -> tuple[str, str]:
    icon = _ICONS.get(ev["kind"], "·")
    return ev["kind"], f"{icon} {ev['text']}"


def run_dashboard(root, sup) -> bool:
    """Per-agent pane TUI. Returns False if prompt_toolkit isn't usable."""
    if not sys.stdout.isatty():
        return False
    try:
        from prompt_toolkit.application import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import DynamicContainer, HSplit, Layout, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.widgets import Frame
    except Exception:  # noqa: BLE001
        return False

    panes: dict[str, deque] = {}      # agent -> deque[(kind, text)]
    seen: dict[str, int] = {}          # run_id -> events consumed
    state = {"running": []}            # current running agent names

    def render(agent: str):
        lines = list(panes.get(agent, []))
        rows = shutil.get_terminal_size((100, 30)).lines
        budget = max(3, (rows - 4) // max(1, len(state["running"])) - 2)
        out = []
        for kind, text in lines[-budget:]:
            out.append((_STYLE.get(kind, ""), text + "\n"))
        return out or [("fg:ansibrightblack", "(idle)\n")]

    def body():
        names = state["running"]
        if not names:
            return HSplit([Window(FormattedTextControl(
                [("fg:ansibrightblack", "\n  no agents running — start one in the host shell "
                  "(/start <name>) or just send a goal.\n")]))])
        frames = []
        for name in names:
            frames.append(Frame(
                Window(FormattedTextControl(lambda n=name: render(n)), wrap_lines=True),
                title=name,
            ))
        return HSplit(frames)

    header = Window(FormattedTextControl(
        [("bold", " AgentSpace monitor "), ("fg:ansibrightblack", " — one pane per agent · q to quit")]),
        height=1)

    kb = KeyBindings()

    @kb.add("q")
    @kb.add("c-c")
    def _(event):
        event.app.exit()

    app = Application(
        layout=Layout(HSplit([header, DynamicContainer(body)])),
        key_bindings=kb,
        full_screen=True,
        refresh_interval=0.5,
    )

    stop = threading.Event()

    def poll():
        while not stop.is_set():
            running = []
            for spec in registry.list_agents(root):
                if not sup.is_running(spec.name):
                    continue
                running.append(spec.name)
                panes.setdefault(spec.name, deque(maxlen=PANE_MAX))
                res = sup.list_runs(spec.name)
                if not res["ok"]:
                    continue
                for summary in reversed(res["data"]["runs"]):
                    rid = summary["run_id"]
                    if seen.get(rid, 0) >= summary["events"] and summary["status"] == "running":
                        continue
                    detail = sup.get_run(spec.name, rid)
                    if not detail["ok"]:
                        continue
                    events = detail["data"]["events"]
                    for ev in events[seen.get(rid, 0):]:
                        panes[spec.name].append(_line_for(ev))
                    seen[rid] = len(events)
                    if detail["data"]["status"] in ("done", "error"):
                        out = (detail["data"].get("result") or {}).get("output_text", "")
                        if out and seen.get(rid + "_r") is None:
                            panes[spec.name].append(("reply", f"⇒ {out[:300]}"))
                            seen[rid + "_r"] = 1
            state["running"] = running
            app.invalidate()
            stop.wait(0.5)

    t = threading.Thread(target=poll, daemon=True)
    t.start()
    try:
        app.run()
    finally:
        stop.set()
    return True


def _flat_feed(root, sup) -> None:
    """Fallback: a single timestamped stream (non-TTY / no prompt_toolkit)."""
    seen: dict[str, int] = {}
    print("AgentSpace monitor (flat feed — Ctrl-C to quit)\n")
    try:
        while True:
            for spec in registry.list_agents(root):
                if not sup.is_running(spec.name):
                    continue
                res = sup.list_runs(spec.name)
                if not res["ok"]:
                    continue
                for summary in reversed(res["data"]["runs"]):
                    rid = summary["run_id"]
                    if seen.get(rid, 0) >= summary["events"] and summary["status"] == "running":
                        continue
                    detail = sup.get_run(spec.name, rid)
                    if not detail["ok"]:
                        continue
                    events = detail["data"]["events"]
                    for ev in events[seen.get(rid, 0):]:
                        icon = _ICONS.get(ev["kind"], "·")
                        print(f"[{time.strftime('%H:%M:%S')}] {spec.name:<14} {icon} {ev['text'][:110]}")
                    seen[rid] = len(events)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nbye.")


def main() -> None:
    root = paths.repo_root()
    sup = Supervisor(root)
    if not run_dashboard(root, sup):
        _flat_feed(root, sup)


if __name__ == "__main__":
    main()
