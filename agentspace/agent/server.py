"""The agent's HTTP API — a minimal Responses-style server.

Each agent process runs one of these (via uvicorn). The host talks to it over HTTP.

Turns run **asynchronously**: `POST /responses` starts the turn in a background
thread and returns a `run_id` immediately, so the caller never blocks. Progress is
exposed as a growing list of events per run:

  POST /responses            -> {run_id, session_id, status:"running"}   (?wait=true to block)
  GET  /runs                 -> recent runs (summaries)
  GET  /runs/{run_id}        -> {status, session_id, events[], result?}
  GET  /health               -> liveness
  GET  /sessions[/{id}]      -> inspect memory
"""

from __future__ import annotations

import os
import threading
import uuid
from collections import OrderedDict
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request

from agentspace.agent.config import AgentSpec
from agentspace.agent.loop import Agent
from agentspace.agent.tools import registry
from agentspace.common.schemas import HealthResponse, ResponsesRequest

MAX_RUNS_KEPT = 100


def _require_token(request: Request) -> None:
    """Bearer-token auth, active only when AGENTSPACE_TOKEN is set (i.e. remote).

    Local runs leave the env unset → no auth, unchanged. `/health` stays open so
    platform health checks and host liveness probes work without the token.
    """
    token = os.environ.get("AGENTSPACE_TOKEN")
    if not token or request.url.path == "/health":
        return
    if request.headers.get("Authorization") != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="unauthorized")


class Run:
    """In-memory record of one (possibly in-flight) turn."""

    def __init__(self, run_id: str, session_id: str, prompt: str):
        self.id = run_id
        self.session_id = session_id
        self.prompt = prompt
        self.status = "running"  # running | done | error
        self.events: list[dict] = []
        self.result: dict | None = None

    def emit(self, kind: str, text: str) -> None:
        self.events.append({"i": len(self.events), "kind": kind, "text": text})

    def summary(self) -> dict:
        last = self.events[-1] if self.events else None
        return {
            "run_id": self.id,
            "session_id": self.session_id,
            "status": self.status,
            "prompt": self.prompt[:80],
            "events": len(self.events),
            "last": last,
        }

    def detail(self) -> dict:
        return {
            "run_id": self.id,
            "session_id": self.session_id,
            "status": self.status,
            "prompt": self.prompt,
            "events": self.events,
            "result": self.result,
        }


def create_app(spec: AgentSpec, root: Path) -> FastAPI:
    app = FastAPI(title=f"agentspace:{spec.name}", dependencies=[Depends(_require_token)])
    agent = Agent(spec, root)
    runs: "OrderedDict[str, Run]" = OrderedDict()
    # Serialize turns that share a session so history writes don't clobber.
    session_locks: dict[str, threading.Lock] = {}
    locks_guard = threading.Lock()

    def _session_lock(session_id: str) -> threading.Lock:
        with locks_guard:
            return session_locks.setdefault(session_id, threading.Lock())

    def _execute(run: Run, prompt: str) -> None:
        lock = _session_lock(run.session_id)
        with lock:
            try:
                result = agent.run(prompt, run.session_id, emit=run.emit)
                run.result = result
                run.status = "error" if result["output_text"].startswith("ERROR:") else "done"
            except Exception as exc:  # noqa: BLE001
                run.emit("error", str(exc))
                run.result = {"output_text": f"ERROR: {exc}", "output": [], "usage": {}}
                run.status = "error"

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        tools, _ = registry.assemble(spec)
        tool_names = [t.get("name", t.get("type", "?")) for t in tools]
        tool_names += [s["name"] for s in agent.mcp.tool_schemas]
        return HealthResponse(name=spec.name, model=spec.model, tools=tool_names)

    @app.get("/mcp")
    def mcp_status() -> dict:
        return {
            "agent": spec.name,
            "servers": agent.mcp.status(),
            "tools": [s["name"] for s in agent.mcp.tool_schemas],
        }

    @app.on_event("shutdown")
    def _shutdown() -> None:
        agent.mcp.close()

    @app.post("/responses")
    def responses(req: ResponsesRequest, wait: bool = False) -> dict:
        session_id = req.session_id or agent.sessions.new_id()
        run = Run("run_" + uuid.uuid4().hex[:10], session_id, req.input)
        runs[run.id] = run
        while len(runs) > MAX_RUNS_KEPT:
            runs.popitem(last=False)

        if wait:
            _execute(run, req.input)
            return run.detail()

        threading.Thread(target=_execute, args=(run, req.input), daemon=True).start()
        return {"run_id": run.id, "session_id": session_id, "status": "running"}

    @app.get("/runs")
    def list_runs() -> dict:
        return {"agent": spec.name, "runs": [r.summary() for r in reversed(runs.values())]}

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        run = runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run.detail()

    @app.get("/sessions")
    def list_sessions() -> dict:
        return {"agent": spec.name, "sessions": agent.sessions.list_ids()}

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str) -> dict:
        if not agent.sessions.exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        return {"session_id": session_id, "messages": agent.sessions.load(session_id)}

    return app
