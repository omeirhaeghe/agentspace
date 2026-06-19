"""The `image_search` tool: find images on the web (keyless, via Openverse).

Uses the Openverse API (api.openverse.org) — ~800M openly-licensed images, no API
key required. Returns a markdown list with inline image links (![](thumb)) plus the
source page and license for each hit, so a host that renders markdown shows them
inline.
"""

from __future__ import annotations

import httpx

ENDPOINT = "https://api.openverse.org/v1/images/"
TIMEOUT = 20
DEFAULT_N = 6
MAX_N = 20

SCHEMA = {
    "name": "image_search",
    "description": (
        "Search the web for images by keyword and return matching results as markdown "
        "(inline thumbnail, title, source page, license). Use when the user wants to "
        "find or show pictures of something."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for, e.g. 'golden gate bridge fog'."},
            "count": {
                "type": "integer",
                "description": f"How many images to return (1-{MAX_N}, default {DEFAULT_N}).",
            },
        },
        "required": ["query"],
    },
}


def handler(ctx, query: str, count: int = DEFAULT_N) -> str:
    query = (query or "").strip()
    if not query:
        return "ERROR: query is required"
    n = max(1, min(int(count), MAX_N))
    try:
        resp = httpx.get(
            ENDPOINT,
            params={"q": query, "page_size": n},
            timeout=TIMEOUT,
            headers={"User-Agent": "AgentSpace image_search"},
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except httpx.HTTPError as exc:
        return f"ERROR: image search failed: {exc}"
    except ValueError:
        return "ERROR: image search returned an unreadable response"

    if not results:
        return f"No images found for '{query}'."

    lines = [f"{len(results)} image(s) for '{query}':\n"]
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "untitled").strip()
        thumb = r.get("thumbnail") or r.get("url") or ""
        page = r.get("foreign_landing_url") or r.get("url") or ""
        lic = r.get("license", "")
        lic_v = r.get("license_version", "")
        creator = r.get("creator") or "unknown"
        license_str = f"{lic} {lic_v}".strip().upper()
        lines.append(
            f"{i}. **{title}** — by {creator} ({license_str or 'see source'})\n"
            f"   ![{title}]({thumb})\n"
            f"   source: {page}"
        )
    return "\n".join(lines)
