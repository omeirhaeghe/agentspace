"""The `web_fetch` tool: fetch a URL and return its readable text content.

Unlike `http_fetch` (which returns the raw response body, HTML and all),
`web_fetch` strips scripts/styles/markup and returns clean, readable page text —
the equivalent of "pull full page contents" for the model to read.
"""

from __future__ import annotations

import html
import re

import httpx

MAX_CHARS = 50_000
TIMEOUT = 25

_SCRIPT_STYLE = re.compile(r"<(script|style|noscript|template)\b[^>]*>.*?</\1>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_BLANKS = re.compile(r"\n\s*\n\s*\n+")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)

SCHEMA = {
    "name": "web_fetch",
    "description": (
        "Fetch a web page (or any URL) and return its full readable text content with "
        "markup stripped. Use this to read an article, doc, or page in detail after a "
        "web_search — for raw API/JSON responses use http_fetch instead."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The http/https URL to fetch."},
            "max_chars": {
                "type": "integer",
                "description": f"Max characters of text to return (default {MAX_CHARS}).",
            },
        },
        "required": ["url"],
    },
}


def _to_text(body: str) -> str:
    body = _SCRIPT_STYLE.sub(" ", body)
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
    body = re.sub(r"</(p|div|li|h[1-6]|tr|section|article)>", "\n", body, flags=re.I)
    body = _TAG.sub("", body)
    body = html.unescape(body)
    body = "\n".join(line.strip() for line in body.splitlines())
    return _BLANKS.sub("\n\n", body).strip()


def handler(ctx, url: str, max_chars: int = MAX_CHARS) -> str:
    if not url.lower().startswith(("http://", "https://")):
        return "ERROR: url must start with http:// or https://"
    try:
        resp = httpx.get(
            url,
            timeout=TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (AgentSpace web_fetch)"},
        )
    except httpx.HTTPError as exc:
        return f"ERROR: fetch failed: {exc}"

    ctype = resp.headers.get("content-type", "")
    raw = resp.text
    if "html" in ctype.lower() or raw.lstrip()[:1] == "<":
        title_m = _TITLE.search(raw)
        title = html.unescape(_TAG.sub("", title_m.group(1)).strip()) if title_m else ""
        text = _to_text(raw)
        text = f"# {title}\n\n{text}" if title else text
    else:
        text = raw  # already plain text/json

    limit = max(1_000, int(max_chars))
    if len(text) > limit:
        text = text[:limit] + f"\n…[truncated, {len(text)} chars total]"
    return f"{resp.url}\nHTTP {resp.status_code} · {ctype or '?'}\n\n{text}"
