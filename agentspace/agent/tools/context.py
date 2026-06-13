"""The runtime context passed to every tool handler as its first argument."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ToolContext:
    root: Path
    workdir: Path
    skills_dir: Path
    allowed_skills: list[str]
    agent_name: str
