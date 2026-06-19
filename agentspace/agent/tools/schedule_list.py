"""The `schedule_list` tool: show currently scheduled jobs."""

from __future__ import annotations

from agentspace.common.paths import repo_root
from agentspace.common.schedule import JobStore

SCHEMA = {
    "name": "schedule_list",
    "description": "List all currently scheduled (timed/recurring) jobs with their id, "
    "goal, timing, and next run time.",
    "input_schema": {"type": "object", "properties": {}},
}


def handler(ctx) -> str:
    root = getattr(ctx, "root", None) or repo_root()
    jobs = JobStore(root).list()
    if not jobs:
        return "No scheduled jobs."
    return f"{len(jobs)} scheduled job(s):\n" + "\n".join(j.describe() for j in jobs)
