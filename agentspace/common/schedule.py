"""Shared scheduling core: the job store and the NL time parser.

This lives in `common` because two processes use it: the `scheduler` *agent*
(via the schedule_* tools) creates/lists/cancels jobs, while the host's `Ticker`
reads the same store to fire jobs when they come due. The file is the source of
truth and every access is flock-guarded, so the two processes don't clobber it.

A *job* carries a natural-language `goal` handed to the conductor on each fire, so
"fetch cnn.com and summarize the headlines" routes itself to the right agent.
"""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

try:
    import fcntl  # POSIX (macOS/Linux)
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

from agentspace.common.paths import runtime_dir

# ---------------------------------------------------------------------------
# Natural-language schedule parsing
# ---------------------------------------------------------------------------

_UNIT_SECONDS = {
    "second": 1, "seconds": 1, "sec": 1, "secs": 1, "s": 1,
    "minute": 60, "minutes": 60, "min": 60, "mins": 60, "m": 60,
    "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600, "h": 3600,
    "day": 86400, "days": 86400, "d": 86400,
    "week": 604800, "weeks": 604800, "wk": 604800, "w": 604800,
}
_UNITS_RE = "seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|wks?|s|m|h|d|w"

_INTERVAL_RE = re.compile(rf"\b(?:every|each)\s+(?:(\d+)\s*)?({_UNITS_RE})\b", re.I)
_NAMED_INTERVAL = {"hourly": 3600, "daily": 86400, "weekly": 604800, "nightly": 86400}
_NAMED_RE = re.compile(r"\b(hourly|daily|weekly|nightly)\b", re.I)
_AT_RE = re.compile(r"\b(?:at|@)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)
_NOON_RE = re.compile(r"\b(noon|midnight)\b", re.I)
_IN_RE = re.compile(rf"\bin\s+(\d+)\s*({_UNITS_RE})\b", re.I)
_FOR_NEXT_RE = re.compile(rf"\bfor\s+(?:the\s+)?next\s+(\d+)\s*({_UNITS_RE})\b", re.I)
_UNTIL_RE = re.compile(r"\buntil\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)
_TIMES_RE = re.compile(r"\b(\d+)\s*(?:times?|x)\b", re.I)
_TODAY_RE = re.compile(r"\btoday\b", re.I)
_TONIGHT_RE = re.compile(r"\btonight\b", re.I)
_THIS_WEEK_RE = re.compile(r"\bthis\s+week\b", re.I)
_TOMORROW_RE = re.compile(r"\btomorrow\b", re.I)
_INTENT_RE = re.compile(r"\b(schedule|remind me)\b", re.I)


@dataclass
class Schedule:
    kind: str                     # "interval" | "once"
    interval: int | None = None   # seconds, for interval jobs
    first_run: float = 0.0        # epoch of the first fire
    until: float | None = None    # epoch after which the job stops
    remaining: int | None = None  # run-count cap
    label: str = ""               # human-readable summary


def _resolve_at(now: datetime, hour: int, minute: int, tomorrow: bool) -> datetime:
    base = now + timedelta(days=1) if tomorrow else now
    cand = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if not tomorrow and cand <= now:
        cand += timedelta(days=1)
    return cand


def _end_of_today(now: datetime) -> datetime:
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def _to_24h(hour: int, minute: int, ampm: str | None) -> tuple[int, int]:
    ap = (ampm or "").lower()
    if ap == "pm" and hour != 12:
        hour += 12
    elif ap == "am" and hour == 12:
        hour = 0
    return hour % 24, minute


def _human_interval(seconds: int) -> str:
    for secs, name in ((604800, "week"), (86400, "day"), (3600, "hour"),
                       (60, "minute"), (1, "second")):
        if seconds % secs == 0:
            n = seconds // secs
            return f"{n} {name}{'s' if n != 1 else ''}" if n != 1 else name
    return f"{seconds}s"


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%-I:%M%p").lower()


def parse_schedule(text: str, now: float | None = None) -> tuple[Schedule, str] | None:
    """Parse a time phrase (optionally with the goal mixed in).

    Returns (Schedule, leftover_text) if `text` carries a real timing cue
    (recurrence, at-time, in-delta, or explicit "schedule"/"remind me"),
    else None. `leftover_text` is whatever remains after the time words are
    stripped — useful when goal and timing arrive in one string.
    """
    now_epoch = time.time() if now is None else now
    now_dt = datetime.fromtimestamp(now_epoch)
    spans: list[tuple[int, int]] = []

    interval: int | None = None
    m = _INTERVAL_RE.search(text)
    if m:
        n = int(m.group(1)) if m.group(1) else 1
        interval = n * _UNIT_SECONDS[m.group(2).lower()]
        spans.append(m.span())
    elif (nm := _NAMED_RE.search(text)):
        interval = _NAMED_INTERVAL[nm.group(1).lower()]
        spans.append(nm.span())

    tomorrow = bool(_TOMORROW_RE.search(text))
    at_dt: datetime | None = None
    if (nm := _NOON_RE.search(text)):
        at_dt = _resolve_at(now_dt, 12 if nm.group(1).lower() == "noon" else 0, 0, tomorrow)
        spans.append(nm.span())
    elif (am := _AT_RE.search(text)):
        hh, mm = _to_24h(int(am.group(1)), int(am.group(2) or 0), am.group(3))
        at_dt = _resolve_at(now_dt, hh, mm, tomorrow)
        spans.append(am.span())

    in_delta: int | None = None
    if interval is None and (im := _IN_RE.search(text)):
        in_delta = int(im.group(1)) * _UNIT_SECONDS[im.group(2).lower()]
        spans.append(im.span())

    has_intent = bool(_INTENT_RE.search(text))
    if interval is None and at_dt is None and in_delta is None and not has_intent:
        return None

    until: float | None = None
    remaining: int | None = None
    bound_label = ""

    if (fm := _FOR_NEXT_RE.search(text)):
        until = now_epoch + int(fm.group(1)) * _UNIT_SECONDS[fm.group(2).lower()]
        spans.append(fm.span())
        bound_label = f"for the next {fm.group(1)} {fm.group(2)}"
    if (um := _UNTIL_RE.search(text)):
        hh, mm = _to_24h(int(um.group(1)), int(um.group(2) or 0), um.group(3))
        until = _resolve_at(now_dt, hh, mm, False).timestamp()
        spans.append(um.span())
        bound_label = f"until {_fmt_time(datetime.fromtimestamp(until))}"
    if _TODAY_RE.search(text) or _TONIGHT_RE.search(text):
        until = _end_of_today(now_dt).timestamp()
        for rx in (_TODAY_RE, _TONIGHT_RE):
            if (b := rx.search(text)):
                spans.append(b.span())
        bound_label = "today"
    if (wm := _THIS_WEEK_RE.search(text)):
        until = (now_dt + timedelta(days=7 - now_dt.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0).timestamp()
        spans.append(wm.span())
        bound_label = "this week"
    if (tm := _TIMES_RE.search(text)):
        remaining = int(tm.group(1))
        spans.append(tm.span())
        bound_label = f"{remaining}×"

    if tomorrow and at_dt is not None:
        for b in _TOMORROW_RE.finditer(text):
            spans.append(b.span())

    leftover = _strip_spans(text, spans)

    if interval is not None:
        first = at_dt.timestamp() if at_dt is not None else now_epoch
        label = f"every {_human_interval(interval)}"
        if at_dt is not None:
            label += f", starting {_fmt_time(at_dt)}"
        if bound_label:
            label += f" {bound_label}"
        return Schedule("interval", interval, first, until, remaining, label), leftover
    if at_dt is not None:
        day = "tomorrow" if at_dt.date() > now_dt.date() else "today"
        return Schedule("once", None, at_dt.timestamp(), None, None,
                        f"once at {_fmt_time(at_dt)} {day}"), leftover
    if in_delta is not None:
        return Schedule("once", None, now_epoch + in_delta, None, None,
                        f"once in {_human_interval(in_delta)}"), leftover
    return None


def _strip_spans(text: str, spans: list[tuple[int, int]]) -> str:
    out, last = [], 0
    for s, e in sorted(spans):
        if s < last:
            continue
        out.append(text[last:s])
        last = e
    out.append(text[last:])
    cleaned = " ".join("".join(out).split())
    cleaned = re.sub(r"^(?:and|then|to|please|,)\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+(?:and|then|,)\s*$", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^remind me (?:to )?", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^schedule (?:a |an )?", "", cleaned, flags=re.I)
    return cleaned.strip(" ,.")


# ---------------------------------------------------------------------------
# Jobs and the file-backed store (cross-process source of truth)
# ---------------------------------------------------------------------------


@dataclass
class Job:
    id: str
    goal: str
    kind: str                       # "interval" | "once"
    next_run: float
    interval: int | None = None
    until: float | None = None
    remaining: int | None = None
    label: str = ""
    created: float = field(default_factory=time.time)
    last_run: float | None = None
    runs: int = 0
    paused: bool = False

    def describe(self, now: float | None = None) -> str:
        now = time.time() if now is None else now
        nxt = datetime.fromtimestamp(self.next_run)
        when = nxt.strftime("%a %-I:%M%p").lower() if self.next_run - now > 36000 \
            else _fmt_time(nxt)
        state = " (paused)" if self.paused else ""
        runs = f" · {self.runs} run(s)" if self.runs else ""
        return f"{self.id}{state}: {self.goal!r} — {self.label}; next {when}{runs}"


class JobStore:
    """Flock-guarded JSON store shared by the agent tools and the host ticker."""

    def __init__(self, root: Path):
        self.file = runtime_dir(root) / "scheduler" / "jobs.json"

    @contextmanager
    def _locked(self):
        """Yield (counter, {id: Job}); persist whatever it contains on exit."""
        self.file.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.file.with_suffix(".lock")
        lock_fp = open(lock_path, "w")
        try:
            if fcntl is not None:
                fcntl.flock(lock_fp, fcntl.LOCK_EX)
            counter, jobs = self._read()
            box = {"counter": counter, "jobs": jobs}
            yield box
            self._write(box["counter"], box["jobs"])
        finally:
            if fcntl is not None:
                fcntl.flock(lock_fp, fcntl.LOCK_UN)
            lock_fp.close()

    def _read(self) -> tuple[int, dict[str, Job]]:
        if not self.file.exists():
            return 0, {}
        try:
            data = json.loads(self.file.read_text())
        except (json.JSONDecodeError, OSError):
            return 0, {}
        jobs = {}
        for raw in data.get("jobs", []):
            job = Job(**{k: raw.get(k) for k in Job.__dataclass_fields__})
            jobs[job.id] = job
        return data.get("counter", 0), jobs

    def _write(self, counter: int, jobs: dict[str, Job]) -> None:
        payload = {"counter": counter, "jobs": [asdict(j) for j in jobs.values()]}
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        os.replace(tmp, self.file)

    # -- mutations (used by the agent's tools) ------------------------------
    def add(self, goal: str, sched: Schedule) -> Job:
        with self._locked() as box:
            box["counter"] += 1
            jid = f"s{box['counter']}"
            job = Job(id=jid, goal=goal, kind=sched.kind, next_run=sched.first_run,
                      interval=sched.interval, until=sched.until,
                      remaining=sched.remaining, label=sched.label)
            box["jobs"][jid] = job
            return job

    def remove(self, jid: str) -> bool:
        with self._locked() as box:
            return box["jobs"].pop(jid, None) is not None

    def set_paused(self, jid: str, paused: bool) -> bool:
        with self._locked() as box:
            job = box["jobs"].get(jid)
            if job:
                job.paused = paused
            return job is not None

    def clear(self) -> int:
        with self._locked() as box:
            n = len(box["jobs"])
            box["jobs"].clear()
            return n

    def list(self) -> list[Job]:
        _, jobs = self._read()
        return sorted(jobs.values(), key=lambda j: j.next_run)

    def get(self, jid: str) -> Job | None:
        return self._read()[1].get(jid)

    # -- used by the host ticker --------------------------------------------
    def due_and_advance(self, now: float) -> list[Job]:
        """Atomically pop/advance jobs that are due; return snapshots to fire."""
        fired: list[Job] = []
        with self._locked() as box:
            for jid, job in list(box["jobs"].items()):
                if job.paused or job.next_run > now:
                    continue
                if job.until is not None and job.until < now:
                    box["jobs"].pop(jid, None)
                    continue
                fired.append(Job(**asdict(job)))  # snapshot before mutation
                job.runs += 1
                job.last_run = now
                done = job.kind == "once"
                if job.remaining is not None:
                    job.remaining -= 1
                    done = done or job.remaining <= 0
                if job.kind == "interval":
                    nxt = job.next_run + (job.interval or 60)
                    job.next_run = nxt if nxt > now else now + (job.interval or 60)
                    if job.until is not None and job.next_run > job.until:
                        done = True
                if done:
                    box["jobs"].pop(jid, None)
        return fired
