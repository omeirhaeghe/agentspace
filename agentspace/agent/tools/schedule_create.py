"""The `schedule_create` tool: register a timed or recurring agent run.

Splits a request into WHAT to run (`goal`) and WHEN (`when`). The host's ticker
later hands `goal` to the conductor at each fire, so it routes to whatever agent
fits ("check google stock" → portfolio; "summarize cnn headlines" → researcher).
"""

from __future__ import annotations

from agentspace.common.paths import repo_root
from agentspace.common.schedule import JobStore, parse_schedule

SCHEMA = {
    "name": "schedule_create",
    "description": (
        "Schedule an agent run to fire later or on a repeating interval. Provide the "
        "action to perform as `goal`, and the timing as `when` in plain English. "
        "Supported timing: recurring ('every hour', 'every 30 minutes', 'daily'), "
        "one-shot ('at 3pm', 'in 10 minutes', 'tomorrow at 9am'), and bounds "
        "('today', 'until 5pm', 'for the next 3 hours', '5 times'). "
        "Examples: goal='check google stock', when='at 3pm'; "
        "goal='fetch cnn.com and summarize the headlines', when='every hour today'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": "The action to run each time, with NO timing words, e.g. "
                "'check stock quotes for AAPL'.",
            },
            "when": {
                "type": "string",
                "description": "The timing phrase, e.g. 'every hour today', 'at 3pm', "
                "'in 10 minutes'.",
            },
        },
        "required": ["goal", "when"],
    },
}


def handler(ctx, goal: str, when: str) -> str:
    goal = (goal or "").strip()
    if not goal:
        return "ERROR: goal is required (what should run)."
    parsed = parse_schedule(when or "")
    if parsed is None:
        # maybe the goal and timing came mixed together in `when`
        parsed = parse_schedule(f"{goal} {when}".strip())
        if parsed is None:
            return (
                f"ERROR: couldn't find a time in {when!r}. Try phrasings like "
                "'every hour', 'at 3pm', 'in 10 minutes', or 'every 30m today'."
            )
    sched, leftover = parsed
    if not goal and leftover:
        goal = leftover
    root = getattr(ctx, "root", None) or repo_root()
    job = JobStore(root).add(goal, sched)
    return f"Scheduled {job.id}: {goal!r} — {sched.label}."
