"""Cloud entrypoint: run one agent as a web service on 0.0.0.0:$PORT.

One image runs any agent, selected by environment so the same build can back many
Render services:

    AGENTSPACE_AGENT=<name>    which agent to serve (required)
    PORT=<port>               port to bind (the platform sets this; default 8000)
    AGENTSPACE_TOKEN=<secret> if set, all routes but /health require a bearer token
    ANTHROPIC_API_KEY=...      the agent's model access

(The local `python -m agentspace.agent` entrypoint stays bound to 127.0.0.1.)
"""

from __future__ import annotations

import os

import uvicorn

from agentspace.agent.config import AgentSpec
from agentspace.agent.server import create_app
from agentspace.common import paths


def main() -> None:
    root = paths.repo_root()
    name = os.environ.get("AGENTSPACE_AGENT")
    if not name:
        raise SystemExit("AGENTSPACE_AGENT env var is required (which agent to serve)")
    cfg = paths.agents_dir(root) / name / "agent.yaml"
    if not cfg.is_file():
        raise SystemExit(f"no such agent: {name} (looked for {cfg})")
    spec = AgentSpec.from_yaml(cfg)
    port = int(os.environ.get("PORT", "8000"))
    print(f"[serve] {spec.name} on 0.0.0.0:{port} (model={spec.model})", flush=True)
    uvicorn.run(create_app(spec, root), host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
