"""Two-way Telegram control: drive the conductor from your phone.

When `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set, this background thread
long-polls Telegram for messages you send the bot, hands each one to the same
conductor the REPL uses, and texts the reply back. It is the inbound half of the
`send_notification` Telegram channel (the outbound half).

Security: only messages from the configured chat id are accepted — anyone else
who finds the bot is ignored.
"""

from __future__ import annotations

import os
import threading
from typing import Callable

import httpx

POLL_TIMEOUT = 25      # Telegram long-poll seconds
MAX_REPLY = 3900       # Telegram caps messages at 4096 chars


class TelegramBridge:
    def __init__(self, orch, log: Callable[[str], None] = print):
        self.orch = orch
        self.log = log
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset: int | None = None

    def available(self) -> bool:
        return bool(self.token and self.chat_id)

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        if not self.available() or (self._thread and self._thread.is_alive()):
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # -- telegram api --------------------------------------------------------
    def _api(self, method: str, http_timeout: float = 15, **params):
        """Call a Bot API method. `http_timeout` is the httpx socket timeout;
        any Telegram query params (including its own long-poll `timeout`) go in
        **params. None-valued params are dropped."""
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        params = {k: v for k, v in params.items() if v is not None}
        r = httpx.get(url, params=params, timeout=http_timeout)
        r.raise_for_status()
        return r.json()

    def send(self, text: str) -> None:
        """Public: push a message to the configured chat (used for replies)."""
        if not self.available():
            return
        if len(text) > MAX_REPLY:
            text = text[:MAX_REPLY] + "\n…(truncated)"
        try:
            httpx.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text},
                timeout=15,
            )
        except httpx.HTTPError as exc:
            self.log(f"[telegram] send failed: {exc}")

    # -- poll loop -----------------------------------------------------------
    def _drain_backlog(self) -> None:
        """Skip messages that arrived before the host started."""
        try:
            data = self._api("getUpdates", http_timeout=20, offset=-1, timeout=0)
            results = data.get("result", [])
            if results:
                self._offset = results[-1]["update_id"] + 1
        except (httpx.HTTPError, KeyError, ValueError):
            pass

    def _loop(self) -> None:
        self._drain_backlog()
        self.log("📲 telegram bridge on — message your bot to drive the conductor.")
        while not self._stop.is_set():
            try:
                data = self._api(
                    "getUpdates", http_timeout=POLL_TIMEOUT + 10,
                    offset=self._offset, timeout=POLL_TIMEOUT,
                    allowed_updates='["message"]',
                )
            except httpx.HTTPError:
                self._stop.wait(3)
                continue
            for upd in data.get("result", []):
                self._offset = upd["update_id"] + 1
                self._dispatch(upd.get("message") or {})

    def _dispatch(self, msg: dict) -> None:
        text = (msg.get("text") or "").strip()
        chat = str((msg.get("chat") or {}).get("id", ""))
        if not text:
            return
        if chat != str(self.chat_id):
            self.log(f"[telegram] ignored message from unauthorized chat {chat}")
            return
        if text in ("/start", "/help"):
            self.send(
                "AgentSpace bridge. Send a goal in plain English and I'll route it "
                "through the conductor, e.g.:\n"
                "• what's on my schedule?\n"
                "• research the F1 standings and summarize\n"
                "• check AAPL and tell me if it's below 180 every hour today"
            )
            return
        threading.Thread(target=self._run_goal, args=(text,), daemon=True).start()

    def _run_goal(self, text: str) -> None:
        self.log(f"📲 telegram> {text}")
        self.send("🧭 on it…")
        try:
            final = self.orch.run(text, lambda kind, t: None)
        except Exception as exc:  # noqa: BLE001
            self.send(f"error: {exc}")
            return
        self.send(final or "(done — no text result)")
        self.log("📲 telegram reply sent")
