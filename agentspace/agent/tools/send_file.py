"""The `send_file` tool: deliver a produced file to the user via Telegram.

Uploads a file (PDF, deck, image, CSV, …) straight into the user's Telegram chat
with `sendDocument` — no cloud storage or link needed; it lands as a downloadable
document on their phone. Use after producing a deliverable the user asked for.

Requires `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` (set via /setup or /settings).
For phone-triggered runs the bridge already auto-attaches new output files, so
call this for deliveries from scheduled jobs or the REPL, or when you want to send
a specific file explicitly.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

TELEGRAM_MAX = 50 * 1024 * 1024  # bot upload cap

SCHEMA = {
    "name": "send_file",
    "description": (
        "Deliver a file you produced to the user via Telegram (it arrives as a "
        "downloadable document on their phone). Pass the path to the file — relative "
        "paths resolve against the output directory. Optionally add a short caption."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file, e.g. 'report.pdf'."},
            "caption": {"type": "string", "description": "Optional short caption."},
        },
        "required": ["path"],
    },
}


def _resolve(ctx, path: str) -> Path | None:
    p = Path(path)
    if p.exists():
        return p
    out = getattr(ctx, "output_dir", None)
    if out:
        for cand in (Path(out) / path, Path(out) / Path(path).name):
            if cand.exists():
                return cand
    return None


def handler(ctx, path: str, caption: str = "") -> str:
    p = _resolve(ctx, path)
    if p is None:
        return f"ERROR: file not found: {path}"
    size = p.stat().st_size
    if size > TELEGRAM_MAX:
        return (f"ERROR: {p.name} is {size // 1024 // 1024}MB, over Telegram's 50MB limit. "
                "Leave it in output/ or upload it elsewhere and send a link.")

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return (f"Telegram not configured — the file is ready at {p}. "
                "Run /setup or /settings telegram to enable phone delivery.")
    try:
        with p.open("rb") as fh:
            r = httpx.post(
                f"https://api.telegram.org/bot{token}/sendDocument",
                data={"chat_id": chat_id, "caption": caption or p.name},
                files={"document": (p.name, fh)},
                timeout=120,
            )
        if r.status_code < 300:
            return f"Sent {p.name} to your Telegram ({size // 1024} KB)."
        return f"ERROR: Telegram rejected the upload (HTTP {r.status_code}): {r.text[:200]}"
    except (httpx.HTTPError, OSError) as exc:
        return f"ERROR: upload failed: {exc}"
