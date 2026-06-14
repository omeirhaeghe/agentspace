"""The runtime context passed to every tool handler as its first argument."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


def _noop(text: str) -> None:  # default progress sink
    return None


@dataclass
class ToolContext:
    root: Path
    workdir: Path
    skills_dir: Path
    allowed_skills: list[str]
    agent_name: str
    # Where tools should write the artifacts they produce (gitignored).
    output_dir: Path = field(default_factory=lambda: Path("output"))
    # Optional live-progress channel: a long-running tool can call
    # ctx.progress("…") to stream interim status into the agent's run events.
    progress: Callable[[str], None] = field(default=_noop)
