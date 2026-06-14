"""Filesystem layout helpers.

The "root" is the AgentSpace repo directory that contains `agents/` and
`skills/`. It is resolved from `AGENTSPACE_ROOT` if set, otherwise by walking up
from the current working directory looking for an `agents/` folder, otherwise the
cwd itself.
"""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    env = os.environ.get("AGENTSPACE_ROOT")
    if env:
        return Path(env).resolve()
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "agents").is_dir():
            return candidate
    return cwd


def agents_dir(root: Path) -> Path:
    return root / "agents"


def skills_dir(root: Path) -> Path:
    return root / "skills"


def runtime_dir(root: Path) -> Path:
    return root / "runtime"


def agent_runtime_dir(root: Path, name: str) -> Path:
    return runtime_dir(root) / name


def tool_contract_path(root: Path) -> Path:
    return root / "docs" / "TOOL_CONTRACT.md"


def agent_contract_path(root: Path) -> Path:
    return root / "docs" / "AGENT_CONTRACT.md"


def generated_tools_dir() -> Path:
    """Directory where PI-authored tools live (inside the package)."""
    return Path(__file__).resolve().parent.parent / "agent" / "tools" / "generated"
