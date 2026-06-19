"""Shared helpers for the conversation-history tools.

Sessions are stored by `SessionStore` as `runtime/<agent>/sessions/<id>.json`, each
a list of Anthropic message dicts. The `_`-prefix keeps the tool registry from
treating this module as a tool (see registry._discover_dir).
"""

from __future__ import annotations

import json
from pathlib import Path

from agentspace.common.paths import agent_runtime_dir, runtime_dir


def session_files(ctx, scope: str) -> list[tuple[str, Path]]:
    """Return (agent_name, session_path) pairs, newest first.

    scope="self" → only the calling agent's sessions; scope="all" → every agent's.
    """
    if scope == "all":
        base = runtime_dir(ctx.root)
        dirs = [(p.name, p / "sessions") for p in sorted(base.glob("*")) if p.is_dir()]
    else:
        dirs = [(ctx.agent_name, agent_runtime_dir(ctx.root, ctx.agent_name) / "sessions")]

    out: list[tuple[str, Path]] = []
    for agent_name, sdir in dirs:
        if sdir.is_dir():
            out.extend((agent_name, p) for p in sdir.glob("*.json"))
    out.sort(key=lambda ap: ap[1].stat().st_mtime, reverse=True)
    return out


def load_messages(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def text_of(content) -> str:
    """Flatten a message's content (string or list of blocks) to plain text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            if block.get("type") == "text" and block.get("text"):
                parts.append(block["text"])
            elif block.get("type") == "tool_result":
                c = block.get("content")
                parts.append(c if isinstance(c, str) else text_of(c))
    return " ".join(p for p in parts if p)


def first_user_message(messages: list[dict]) -> str:
    for m in messages:
        if m.get("role") == "user":
            t = text_of(m.get("content")).strip()
            if t:
                return t
    return ""
