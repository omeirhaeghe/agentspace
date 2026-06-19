"""The `conversation_search` tool: find past conversations by keyword.

Searches stored session transcripts (the agent's memory) for a query and returns
matching snippets with their session id — the equivalent of "retrieve our past
conversations".
"""

from __future__ import annotations

from agentspace.agent.tools._session_history import (
    load_messages,
    session_files,
    text_of,
)

DEFAULT_MAX = 8
SNIPPET = 160

SCHEMA = {
    "name": "conversation_search",
    "description": (
        "Search past conversation transcripts (session memory) for a keyword/phrase and "
        "return matching message snippets with their session id. Use to recall what was "
        "discussed earlier. scope 'self' (default) searches this agent; 'all' searches "
        "every agent's sessions."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keyword or phrase to look for."},
            "scope": {
                "type": "string",
                "enum": ["self", "all"],
                "description": "Whose sessions to search (default 'self').",
            },
            "max_results": {
                "type": "integer",
                "description": f"Max matching snippets to return (default {DEFAULT_MAX}).",
            },
        },
        "required": ["query"],
    },
}


def handler(ctx, query: str, scope: str = "self", max_results: int = DEFAULT_MAX) -> str:
    needle = (query or "").strip().lower()
    if not needle:
        return "ERROR: query is required"
    scope = "all" if scope == "all" else "self"
    limit = max(1, int(max_results))

    hits: list[str] = []
    for agent_name, path in session_files(ctx, scope):
        for msg in load_messages(path):
            text = text_of(msg.get("content"))
            low = text.lower()
            idx = low.find(needle)
            if idx == -1:
                continue
            start = max(0, idx - 40)
            snippet = text[start : start + SNIPPET].replace("\n", " ").strip()
            who = msg.get("role", "?")
            where = f"{agent_name}/{path.stem}" if scope == "all" else path.stem
            hits.append(f"- [{where} · {who}] …{snippet}…")
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break

    if not hits:
        return f"No past conversation matches for '{query}' (scope={scope})."
    return f"{len(hits)} match(es) for '{query}':\n" + "\n".join(hits)
