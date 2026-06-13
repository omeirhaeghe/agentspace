"""Entry point for an agent process.

    python -m agentspace.agent --config agents/<name>/agent.yaml --port 7001

The host's supervisor spawns this; you can also run it directly for debugging.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from agentspace.agent.config import AgentSpec
from agentspace.agent.server import create_app
from agentspace.common import paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a single AgentSpace agent process.")
    parser.add_argument("--config", required=True, help="Path to agent.yaml")
    parser.add_argument("--port", type=int, required=True, help="Port to listen on")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--root", default=None, help="AgentSpace repo root")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else paths.repo_root()
    spec = AgentSpec.from_yaml(Path(args.config).resolve())
    app = create_app(spec, root)

    print(f"[agent:{spec.name}] starting on {args.host}:{args.port} (model={spec.model})", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
