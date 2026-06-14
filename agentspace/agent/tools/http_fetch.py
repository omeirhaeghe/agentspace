"""The `http_fetch` tool: GET a URL and return its body as text."""

from __future__ import annotations

import httpx

MAX_CHARS = 20_000
TIMEOUT = 20

SCHEMA = {
    "name": "http_fetch",
    "description": "HTTP GET a URL and return the response body as text (truncated). Use for "
    "APIs and pages; for rich web content prefer the web_search tool or a fetch MCP server.",
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to fetch (http/https)."}
        },
        "required": ["url"],
    },
}


def handler(ctx, url: str) -> str:
    if not url.lower().startswith(("http://", "https://")):
        return "ERROR: url must start with http:// or https://"
    try:
        resp = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
    except httpx.HTTPError as exc:
        return f"ERROR: fetch failed: {exc}"
    body = resp.text
    if len(body) > MAX_CHARS:
        body = body[:MAX_CHARS] + f"\n…[truncated, {len(resp.text)} chars total]"
    ctype = resp.headers.get("content-type", "?")
    return f"HTTP {resp.status_code} · {ctype}\n\n{body}"
