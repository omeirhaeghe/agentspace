"""Process supervisor: spawn/kill agent processes and talk to them.

Each agent runs as `python -m agentspace.agent`. The supervisor allocates a port,
launches the process (inheriting the environment, including ANTHROPIC_API_KEY),
records pid/port under `runtime/<name>/`, and health-polls until it's ready.
Liveness survives across host restarts because state lives in pid/port files.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from agentspace.common import paths
from agentspace.host import registry


class Supervisor:
    def __init__(self, root: Path):
        self.root = root
        self._procs: dict[str, subprocess.Popen] = {}

    # -- runtime state files -------------------------------------------------
    def _dir(self, name: str) -> Path:
        d = paths.agent_runtime_dir(self.root, name)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _pid_file(self, name: str) -> Path:
        return self._dir(name) / "pid"

    def _port_file(self, name: str) -> Path:
        return self._dir(name) / "port"

    def _log_file(self, name: str) -> Path:
        return self._dir(name) / "server.log"

    def _read_int(self, path: Path) -> int | None:
        try:
            return int(path.read_text().strip())
        except (OSError, ValueError):
            return None

    def pid(self, name: str) -> int | None:
        return self._read_int(self._pid_file(name))

    def port(self, name: str) -> int | None:
        return self._read_int(self._port_file(name))

    # -- liveness ------------------------------------------------------------
    @staticmethod
    def _alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def is_running(self, name: str) -> bool:
        pid = self.pid(name)
        return bool(pid and self._alive(pid))

    def status(self, name: str) -> dict:
        running = self.is_running(name)
        return {
            "name": name,
            "running": running,
            "pid": self.pid(name) if running else None,
            "port": self.port(name) if running else None,
        }

    # -- lifecycle -----------------------------------------------------------
    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def start(self, name: str, ready_timeout: float = 20.0) -> dict:
        if self.is_running(name):
            return {"ok": True, "message": f"{name} already running", "port": self.port(name)}

        cfg = registry.config_path(self.root, name)
        if not cfg.is_file():
            return {"ok": False, "message": f"no such agent: {name}"}

        port = self._free_port()
        log = open(self._log_file(name), "a")  # noqa: SIM115 (kept open for the child)
        log.write(f"\n===== start {time.strftime('%Y-%m-%d %H:%M:%S')} port={port} =====\n")
        log.flush()

        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "agentspace.agent",
                "--config",
                str(cfg),
                "--port",
                str(port),
                "--root",
                str(self.root),
            ],
            cwd=str(self.root),
            stdout=log,
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
        )
        self._procs[name] = proc
        self._pid_file(name).write_text(str(proc.pid))
        self._port_file(name).write_text(str(port))

        # Health-poll until ready.
        deadline = time.monotonic() + ready_timeout
        url = f"http://127.0.0.1:{port}/health"
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                self._clear_files(name)
                return {
                    "ok": False,
                    "message": f"{name} exited during startup (code {proc.returncode}). "
                    f"See `logs {name}`.",
                }
            try:
                if httpx.get(url, timeout=1.0).status_code == 200:
                    return {"ok": True, "message": f"{name} running on :{port}", "port": port}
            except httpx.HTTPError:
                pass
            time.sleep(0.25)

        return {"ok": False, "message": f"{name} did not become healthy in {ready_timeout}s."}

    def stop(self, name: str, timeout: float = 5.0) -> dict:
        pid = self.pid(name)
        if not pid or not self._alive(pid):
            self._clear_files(name)
            return {"ok": True, "message": f"{name} is not running"}
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            return {"ok": False, "message": f"failed to stop {name}: {exc}"}

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self._alive(pid):
            time.sleep(0.1)
        if self._alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        self._procs.pop(name, None)
        self._clear_files(name)
        return {"ok": True, "message": f"{name} stopped"}

    def restart(self, name: str) -> dict:
        self.stop(name)
        return self.start(name)

    def _clear_files(self, name: str) -> None:
        for path in (self._pid_file(name), self._port_file(name)):
            try:
                path.unlink()
            except OSError:
                pass

    # -- talking to the agent ------------------------------------------------
    def send(self, name: str, text: str, session_id: str | None = None,
             wait: bool = False, timeout: float = 300.0) -> dict:
        """Start a turn. Returns immediately with a run_id (async) unless wait=True."""
        port = self.port(name)
        if not self.is_running(name) or not port:
            return {"ok": False, "message": f"{name} is not running. `start {name}` first."}
        body = {"input": text}
        if session_id:
            body["session_id"] = session_id
        url = f"http://127.0.0.1:{port}/responses"
        if wait:
            url += "?wait=true"
        try:
            resp = httpx.post(url, json=body, timeout=timeout if wait else 15.0)
            resp.raise_for_status()
            return {"ok": True, "data": resp.json()}
        except httpx.HTTPError as exc:
            return {"ok": False, "message": f"request to {name} failed: {exc}"}

    def get_run(self, name: str, run_id: str) -> dict:
        return self.get_json(name, f"/runs/{run_id}")

    def list_runs(self, name: str) -> dict:
        return self.get_json(name, "/runs")

    def get_json(self, name: str, path: str, timeout: float = 10.0) -> dict:
        port = self.port(name)
        if not self.is_running(name) or not port:
            return {"ok": False, "message": f"{name} is not running."}
        try:
            resp = httpx.get(f"http://127.0.0.1:{port}{path}", timeout=timeout)
            resp.raise_for_status()
            return {"ok": True, "data": resp.json()}
        except httpx.HTTPError as exc:
            return {"ok": False, "message": f"request to {name} failed: {exc}"}

    def tail_log(self, name: str, n: int = 40) -> str:
        path = self._log_file(name)
        if not path.exists():
            return "(no log yet)"
        lines = path.read_text().splitlines()
        return "\n".join(lines[-n:])

    def running_agents(self) -> list[str]:
        out = []
        for spec in registry.list_agents(self.root):
            if self.is_running(spec.name):
                out.append(spec.name)
        return out
