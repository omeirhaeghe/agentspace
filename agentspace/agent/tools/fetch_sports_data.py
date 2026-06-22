"""The `fetch_sports_data` tool: scores & standings for major leagues (keyless).

Uses ESPN's public site API (site.api.espn.com) — no key required. Returns the
scoreboard (live/recent scores, status) for a league, optionally on a given date.
"""

from __future__ import annotations

import httpx

TIMEOUT = 20

# Friendly league key -> ESPN "{sport}/{league}" path.
LEAGUES = {
    "nfl": "football/nfl",
    "college-football": "football/college-football",
    "cfb": "football/college-football",
    "nba": "basketball/nba",
    "wnba": "basketball/wnba",
    "mens-college-basketball": "basketball/mens-college-basketball",
    "ncaam": "basketball/mens-college-basketball",
    "mlb": "baseball/mlb",
    "nhl": "hockey/nhl",
    "epl": "soccer/eng.1",
    "premier-league": "soccer/eng.1",
    "laliga": "soccer/esp.1",
    "bundesliga": "soccer/ger.1",
    "seriea": "soccer/ita.1",
    "ligue1": "soccer/fra.1",
    "ucl": "soccer/uefa.champions",
    "champions-league": "soccer/uefa.champions",
    "mls": "soccer/usa.1",
    "world-cup": "soccer/fifa.world",
    "fifa-world-cup": "soccer/fifa.world",
    "wc": "soccer/fifa.world",
    "fifa": "soccer/fifa.world",
    "club-world-cup": "soccer/fifa.cwc",
    "cwc": "soccer/fifa.cwc",
}

SCHEMA = {
    "name": "fetch_sports_data",
    "description": (
        "Get current scores, game status, and standings info for a major sports league "
        "(scoreboard from ESPN). Supported leagues: " + ", ".join(sorted(LEAGUES)) + ". "
        "Optionally pass a date (YYYYMMDD) for a specific day's games."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "league": {
                "type": "string",
                "description": "League key, e.g. 'nba', 'nfl', 'epl', 'mlb'.",
            },
            "date": {
                "type": "string",
                "description": "Optional day as YYYYMMDD (e.g. '20260619'). Omit for today's games.",
            },
        },
        "required": ["league"],
    },
}


def _line(event: dict) -> str:
    comps = (event.get("competitions") or [{}])[0]
    status = (comps.get("status") or event.get("status") or {}).get("type", {})
    detail = status.get("shortDetail") or status.get("description") or ""
    teams = comps.get("competitors") or []
    parts = []
    for t in teams:
        name = (t.get("team") or {}).get("displayName") or (t.get("team") or {}).get("name") or "?"
        score = t.get("score", "")
        ha = t.get("homeAway", "")
        tag = "🏠" if ha == "home" else "✈️" if ha == "away" else ""
        parts.append(f"{tag}{name} {score}".strip())
    return f"  {'  vs  '.join(parts) or event.get('name', '?')}  [{detail}]"


def handler(ctx, league: str, date: str | None = None) -> str:
    key = (league or "").strip().lower()
    path = LEAGUES.get(key)
    if not path:
        return f"ERROR: unknown league '{league}'. Try one of: {', '.join(sorted(LEAGUES))}"

    url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
    params = {}
    if date:
        params["dates"] = str(date).strip()
    try:
        resp = httpx.get(url, params=params, timeout=TIMEOUT,
                         headers={"User-Agent": "AgentSpace fetch_sports_data"})
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        return f"ERROR: sports data fetch failed: {exc}"
    except ValueError:
        return "ERROR: sports data returned an unreadable response"

    events = data.get("events") or []
    label = (data.get("leagues") or [{}])[0].get("name") or key.upper()
    when = f" on {date}" if date else " (today)"
    if not events:
        return f"{label}: no games scheduled{when}."

    lines = [f"{label} — {len(events)} game(s){when}:"]
    lines.extend(_line(e) for e in events)
    return "\n".join(lines)
