"""Load an agent's declarative spec from `agents/<name>/agent.yaml`."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class AgentSpec:
    """A declarative agent definition."""

    name: str
    model: str = "claude-sonnet-4-6"
    description: str = ""  # one line; used by the conductor to route tasks
    system_prompt: str = "You are a helpful agent."
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    max_tokens: int = 4096
    can_author_tools: bool = False
    # Where the agent does file/command work. Defaults to the repo root.
    workdir: str | None = None

    @classmethod
    def from_yaml(cls, path: Path) -> "AgentSpec":
        data = yaml.safe_load(path.read_text()) or {}
        # Default the name to the folder name if not specified.
        data.setdefault("name", path.parent.name)
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"{path}: unknown keys in agent.yaml: {sorted(unknown)}")
        return cls(**data)
