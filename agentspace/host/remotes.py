"""Local registry of remotely-deployed agents (deploys.yaml).

Maps agent name -> {url, service_id, provider}. No secrets are stored here — the
bearer token is the AGENTSPACE_TOKEN env var — so it's just local infra state
(gitignored).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from agentspace.common import paths


def load(root: Path) -> dict:
    f = paths.deploys_file(root)
    if not f.exists():
        return {}
    data = yaml.safe_load(f.read_text()) or {}
    return data.get("deploys", {}) or {}


def save(root: Path, deploys: dict) -> None:
    paths.deploys_file(root).write_text(yaml.safe_dump({"deploys": deploys}, sort_keys=True))


def get(root: Path, name: str) -> dict | None:
    return load(root).get(name)


def put(root: Path, name: str, info: dict) -> None:
    deploys = load(root)
    deploys[name] = info
    save(root, deploys)


def remove(root: Path, name: str) -> None:
    deploys = load(root)
    deploys.pop(name, None)
    save(root, deploys)
