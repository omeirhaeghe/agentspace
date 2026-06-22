# Recipes — starter bundles

Seventeen agents is a lot to face on a blank prompt. These are **curated starting points**:
a use case, the agents that cover it, the skills they already carry, and the one
prerequisite you have to flip on. Pick one, type the example goal, and the conductor routes
the rest.

> **Note:** the conductor discovers *every* agent in `agents/` all the time — there's no
> enable/disable. A recipe isn't a mode you switch into; it's "for *this* job, these are the
> agents that matter and here's what to turn on." Just type the goal — or `/start` the
> agents first if you want them warm.

| Recipe | For | Agents | Turn on first |
|---|---|---|---|
| [Research desk](#research-desk) | cited answers → polished docs/decks | `researcher`, `tech-writer`, `doc-writer` | `fetch` MCP (uvx) |
| [Code workbench](#code-workbench) | implement, review, inspect the repo | `coder`, `gitops`, `github` | `git` MCP (uvx); `GITHUB_TOKEN` for GitHub |
| [Data desk](#data-desk) | answer questions from a CSV/dataset | `data-analyst`, `files` | `filesystem` MCP (npx) |
| [Watch & notify](#watch--notify) | watch a condition, ping your phone | `scheduler`, `watchdog`, `researcher` | Telegram (`/setup`) for phone alerts |
| [Everyday assistant](#everyday-assistant) | a from-anywhere driver | `assistant`, `scheduler`, `researcher` | Telegram (`/setup`) to drive from your phone |
| [Product & docs](#product--docs) | PRDs, specs, guides | `tech-writer`, `doc-writer` | nothing |

---

## Research desk

Cited answers for quick lookups, a full search → draft → critique → refine pass for hard
questions — then handed to a writer for a doc or deck.

- **Agents:** `researcher` (web_search, web_fetch, image_search), `tech-writer`, `doc-writer`
- **Skills (already wired):** `web-research`, `summarize`, `technical-writing`, `prd`
- **Turn on first:** the `fetch` MCP server (needs `uvx`); `web_search` runs server-side and
  just needs your `ANTHROPIC_API_KEY`.

```text
research france's odds of winning the world cup and make a cool powerpoint about it
what's the latest stable python release? cite a source
```

## Code workbench

Write and change code, review the diff, and inspect the repo — all in the project dir.

- **Agents:** `coder` (read/write files, `sh`, `python`, can author its own tools), `gitops`
  (git status/diff/log via MCP), `github` (issues/PRs/code search)
- **Skills:** `coding`, `debugging`, `code-review`
- **Turn on first:** the `git` MCP server (needs `uvx`). For `github`, set `GITHUB_TOKEN` and
  flip `enabled: true` in `mcp/servers.yaml`.

```text
add input validation to the upload handler and write a couple of tests
/send gitops "what changed on this branch versus main?"
```

## Data desk

Point it at a file, get reproducible answers computed in Python — not eyeballed.

- **Agents:** `data-analyst` (`python`, reads files, can author tools), `files` (browse/search
  via the filesystem MCP)
- **Skills:** `data-analysis`, `sql`
- **Turn on first:** the `filesystem` MCP server (needs Node / `npx`).

```text
analyze job_search.csv — roles per company, and the median age of a posting?
```

## Watch & notify

The always-on pair: arm a condition, stay silent until it trips, then ping you — on your
phone if Telegram is set up.

- **Agents:** `scheduler` (timed/recurring runs), `watchdog` (checks live data, notifies
  *only* on a trip), `researcher` for richer checks
- **Skills:** `web-research`
- **Turn on first:** nothing required — alerts go to desktop, Slack, and a log out of the
  box. Run `/setup` to add **Telegram** so alerts (and replies) hit your phone.

```text
watch BTC and ping my phone if it cracks $70k, check every 30 minutes
fetch cnn.com every hour today and summarize the top headlines
```

## Everyday assistant

A general driver you can talk to from your desk or your pocket. With Telegram on, text the
bot and it routes through the same conductor.

- **Agents:** `assistant` (chat + `conversation_search` / `recent_chats`), plus `scheduler`
  and `researcher` on tap
- **Skills:** `summarize`
- **Turn on first:** run `/setup` and wire up Telegram to drive it from your phone.

```text
# typed at the prompt, or texted to the bot:
what are france's world cup odds?
remind me to check the deploy in 20 minutes
```

## Product & docs

Decision-grade product writing with house templates.

- **Agents:** `tech-writer` (PRDs/specs/guides), `doc-writer` (creates the file; authors a
  document tool on demand if it lacks one)
- **Skills:** `prd`, `technical-writing`, `summarize`
- **Turn on first:** nothing.

```text
write a PRD for a CLI that converts CSVs into charts
```

---

### …and a few specialists

Some agents are single-purpose and don't need a bundle — just talk to them (the conductor
routes, or `/send` directly):

- **`competitive-analyst`** — researches a market and produces a structured competitive
  landscape report.
- **`job-search`** — finds current openings for a role and appends the top 5 to
  `job_search.csv`.
- **`portfolio-tracker`** — tracks a stock portfolio, fetches quotes, and recommends
  buy/sell/hold.
- **`french-translator`** — turns any text into natural, idiomatic French.
- **`shell-helper`** — runs shell commands and inspects files in the project dir.
- **`tic-tac-toe`** — plays O against you. Because why not.

---

### Prerequisites cheat-sheet

| Thing | Needed for | How |
|---|---|---|
| `ANTHROPIC_API_KEY` | everything (agents call the Messages API) | `export ANTHROPIC_API_KEY=…` |
| `uvx` (from `uv`) | `fetch`, `git` MCP servers | [install uv](https://github.com/astral-sh/uv) |
| `npx` (from Node) | `filesystem` MCP server | install Node.js |
| `GITHUB_TOKEN` | the `github` agent | set it, then `enabled: true` in `mcp/servers.yaml` |
| Telegram bot | phone alerts + driving from your phone | `/setup` (~2 min) |
| `pi-coding-agent` | `write_tool` / `/create-agent` (self-authoring) | `npm i -g @mariozechner/pi-coding-agent` |

Check live status anytime with `/mcp` (server connections) and `/ps` (running agents).
