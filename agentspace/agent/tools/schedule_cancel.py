"""The `schedule_cancel` tool: cancel a scheduled job (or all of them)."""

from __future__ import annotations

from agentspace.common.paths import repo_root
from agentspace.common.schedule import JobStore

SCHEMA = {
    "name": "schedule_cancel",
    "description": "Cancel a scheduled job by its id (e.g. 's3'), or pass 'all' to cancel "
    "every scheduled job. Use schedule_list first to find the id.",
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "The job id to cancel, or 'all'."},
        },
        "required": ["id"],
    },
}


def handler(ctx, id: str) -> str:
    jid = (id or "").strip()
    if not jid:
        return "ERROR: id is required (a job id or 'all')."
    root = getattr(ctx, "root", None) or repo_root()
    store = JobStore(root)
    if jid.lower() == "all":
        n = store.clear()
        return f"Cancelled {n} scheduled job(s)." if n else "No scheduled jobs to cancel."
    return f"Cancelled {jid}." if store.remove(jid) else f"No scheduled job with id {jid!r}."
