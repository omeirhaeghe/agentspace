"""JSON-on-disk session persistence.

A session is an ordered list of Anthropic message dicts (`{"role", "content"}`)
stored at `runtime/<agent>/sessions/<session_id>.json`. This is the agent's
memory: each `/responses` call loads the history, appends the new turns, and saves
it back — the mechanism behind Responses-style statefulness.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path


class SessionStore:
    def __init__(self, agent_runtime_dir: Path):
        self.dir = agent_runtime_dir / "sessions"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.dir / f"{session_id}.json"

    def new_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def exists(self, session_id: str) -> bool:
        return self._path(session_id).exists()

    def load(self, session_id: str) -> list[dict]:
        path = self._path(session_id)
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return []

    def save(self, session_id: str, messages: list[dict]) -> None:
        self._path(session_id).write_text(json.dumps(messages, indent=2))

    def list_ids(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.json"))
