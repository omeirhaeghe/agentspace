"""The `recent_chats` tool: list recent conversations, newest first.

Returns the most recently active sessions with a preview of the opening message and
turn count — the equivalent of "retrieve our recent chats".
"""

from __future__ import annotations

from datetime import datetime, timezone

from agentspace.agent.tools._session_history import (
    first_user_message,
    load_messages,
    session_files,
)

DEFAULT_N = 10
PREVIEW = 100

SCHEMA = {
    "name": "recent_chats",
    "description": (
        "List the most recent conversations (sessions) newest-first, each with its id, "
        "last-active time, turn count, and a preview of the opening message. scope 'self' "
        "(default) lists this agent's chats; 'all' lists every agent's."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "enum": ["self", "all"],
                "description": "Whose chats to list (default 'self').",
            },
            "count": {
                "type": "integer",
                "description": f"How many to list (default {DEFAULT_N}).",
            },
        },
        "required": [],
    },
}


def handler(ctx, scope: str = "self", count: int = DEFAULT_N) -> str:
    scope = "all" if scope == "all" else "self"
    n = max(1, int(count))

    files = session_files(ctx, scope)[:n]
    if not files:
        return f"No conversations found (scope={scope})."

    lines = [f"{len(files)} recent conversation(s) (scope={scope}):"]
    for agent_name, path in files:
        messages = load_messages(path)
        when = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
        preview = first_user_message(messages).replace("\n", " ").strip()[:PREVIEW]
        ident = f"{agent_name}/{path.stem}" if scope == "all" else path.stem
        lines.append(f"- {ident} · {when} · {len(messages)} msgs · \"{preview}…\"")
    return "\n".join(lines)
