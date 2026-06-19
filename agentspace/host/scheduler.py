"""The host-side ticker that fires due scheduled jobs.

This is the only piece of scheduling that must live in the host: an agent is a
request/response process and can neither tick a wall clock nor reach the conductor
to launch other agents. The `scheduler` agent owns understanding and job CRUD (via
the schedule_* tools); this thread just polls the shared `JobStore` and hands each
due job's goal to the conductor, so the fired goal routes itself to the right agent.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from agentspace.common.schedule import Job, JobStore

TICK = 3.0  # seconds between due-checks


class Ticker:
    def __init__(self, root: Path, fire: Callable[[Job], None]):
        self.store = JobStore(root)
        self._fire = fire
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(TICK):
            try:
                due = self.store.due_and_advance(time.time())
            except Exception as exc:  # noqa: BLE001 - never let the ticker die
                print(f"[scheduler] tick error: {exc}", flush=True)
                continue
            for job in due:
                threading.Thread(target=self._fire, args=(job,), daemon=True).start()
