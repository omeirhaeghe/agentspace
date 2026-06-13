"""Discover the agents declared under `agents/`."""

from __future__ import annotations

from pathlib import Path

from agentspace.agent.config import AgentSpec
from agentspace.common import paths


def config_path(root: Path, name: str) -> Path:
    return paths.agents_dir(root) / name / "agent.yaml"


def list_agents(root: Path) -> list[AgentSpec]:
    agents_dir = paths.agents_dir(root)
    specs: list[AgentSpec] = []
    if not agents_dir.is_dir():
        return specs
    for child in sorted(agents_dir.iterdir()):
        cfg = child / "agent.yaml"
        if cfg.is_file():
            try:
                specs.append(AgentSpec.from_yaml(cfg))
            except Exception as exc:  # noqa: BLE001
                print(f"[registry] skipping {cfg}: {exc}")
    return specs


def get_agent(root: Path, name: str) -> AgentSpec | None:
    cfg = config_path(root, name)
    if not cfg.is_file():
        return None
    return AgentSpec.from_yaml(cfg)
