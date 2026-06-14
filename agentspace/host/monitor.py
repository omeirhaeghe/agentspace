"""A separate live console for AgentSpace internals.

Run it in a second terminal alongside the host:

    uv run agentspace-monitor

It polls every running agent's `/runs` endpoint and streams a unified, timestamped
feed of everything happening — each model turn, tool call, PI authoring step, and the
final reply — across all agents at once. Read-only; it never starts or stops anything.
"""

from __future__ import annotations

import time

from agentspace.common import paths
from agentspace.host import registry
from agentspace.host.supervisor import Supervisor

_ICONS = {
    "start": "→", "model": "·", "say": "💬", "tool": "🔧", "tool_done": "✓",
    "progress": "✎", "system": "⚙", "error": "✗", "done": "■",
}

# distinct color per agent so the interleaved feed is readable
_COLORS = ["36", "32", "33", "35", "34", "31"]
_RESET = "\033[0m"
_DIM = "\033[2m"


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _color_for(name: str, table: dict) -> str:
    if name not in table:
        table[name] = _COLORS[len(table) % len(_COLORS)]
    return table[name]


def main() -> None:
    root = paths.repo_root()
    sup = Supervisor(root)
    seen: dict[str, int] = {}          # run_id -> events consumed
    status: dict[str, bool] = {}        # agent -> running?
    colors: dict[str, str] = {}

    print("AgentSpace monitor — live feed across all agents (Ctrl-C to quit)")
    print(f"{_DIM}root: {root}{_RESET}\n")

    try:
        while True:
            for spec in registry.list_agents(root):
                name = spec.name
                col = _color_for(name, colors)
                running = sup.is_running(name)

                if status.get(name) != running:
                    status[name] = running
                    state = f"▶ running :{sup.port(name)}" if running else "■ stopped"
                    print(f"{_DIM}[{_ts()}]{_RESET} \033[{col}m{name:<13}{_RESET} {state}")
                if not running:
                    continue

                res = sup.list_runs(name)
                if not res["ok"]:
                    continue
                for summary in reversed(res["data"]["runs"]):
                    rid = summary["run_id"]
                    if seen.get(rid, 0) >= summary["events"] and summary["status"] == "running":
                        continue
                    detail = sup.get_run(name, rid)
                    if not detail["ok"]:
                        continue
                    run = detail["data"]
                    events = run["events"]
                    start_at = seen.get(rid, 0)
                    for ev in events[start_at:]:
                        icon = _ICONS.get(ev["kind"], "·")
                        print(
                            f"{_DIM}[{_ts()}]{_RESET} \033[{col}m{name:<13}{_RESET} "
                            f"{_DIM}{rid}{_RESET} {icon} {ev['text'][:120]}"
                        )
                    seen[rid] = len(events)
                    if run["status"] in ("done", "error") and start_at < len(events):
                        out = (run.get("result") or {}).get("output_text", "")
                        if out:
                            print(
                                f"{_DIM}[{_ts()}]{_RESET} \033[{col}m{name:<13}{_RESET} "
                                f"⇒ {out[:160]}"
                            )
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nbye.")


if __name__ == "__main__":
    main()
