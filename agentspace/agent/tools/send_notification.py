"""The `send_notification` tool: push a short message to the user.

Delivers through whatever channels are available, best-effort:
- **desktop** — a native macOS notification (via `osascript`), when on darwin.
- **telegram** — to your phone via a bot, if `TELEGRAM_BOT_TOKEN` and
  `TELEGRAM_CHAT_ID` are set (create a bot with @BotFather; get the chat id from
  https://api.telegram.org/bot<token>/getUpdates after messaging the bot once).
- **slack** — POST to `SLACK_WEBHOOK_URL` if that env var is set.
- **log** — always appended to `runtime/notifications.log` as a durable record.

This is what makes scheduled and watchdog runs useful: they can reach you even
when you're not watching the REPL.
"""

from __future__ import annotations

import platform
import subprocess
from datetime import datetime

import httpx

from agentspace.common.paths import runtime_dir

SCHEMA = {
    "name": "send_notification",
    "description": (
        "Send the user a short notification (desktop popup on macOS, Slack if a webhook "
        "is configured, and always logged). Use to alert the user about something that "
        "happened — a watchdog condition tripping, a scheduled job's result, a reminder."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "The notification body (keep it short)."},
            "title": {"type": "string", "description": "Optional title/subject (default 'AgentSpace')."},
        },
        "required": ["message"],
    },
}


def _sanitize(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip()


def _desktop(title: str, message: str) -> bool:
    if platform.system() != "Darwin":
        return False
    script = f'display notification "{_sanitize(message)}" with title "{_sanitize(title)}"'
    try:
        subprocess.run(["osascript", "-e", script], check=True,
                       capture_output=True, timeout=10)
        return True
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return False


def _telegram(title: str, message: str) -> bool:
    import os
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    text = f"*{title}*\n{message}" if title else message
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        return r.status_code < 300
    except httpx.HTTPError:
        return False


def _slack(title: str, message: str) -> bool:
    import os
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return False
    try:
        r = httpx.post(url, json={"text": f"*{title}*\n{message}"}, timeout=10)
        return r.status_code < 300
    except httpx.HTTPError:
        return False


def handler(ctx, message: str, title: str = "AgentSpace") -> str:
    message = (message or "").strip()
    if not message:
        return "ERROR: message is required"

    delivered = []
    if _desktop(title, message):
        delivered.append("desktop")
    if _telegram(title, message):
        delivered.append("telegram")
    if _slack(title, message):
        delivered.append("slack")

    # durable log — always
    try:
        root = getattr(ctx, "root", None)
        log = (runtime_dir(root) if root else runtime_dir(__import__("pathlib").Path("."))) / "notifications.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log.open("a") as fh:
            fh.write(f"[{stamp}] {title}: {message}\n")
        delivered.append("log")
    except OSError:
        pass

    where = ", ".join(delivered) if delivered else "nowhere (no channels available)"
    return f"Notification sent via {where}: {title} — {message}"
