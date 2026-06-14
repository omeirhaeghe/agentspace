<p align="center">
  <img src="docs/logo.svg" alt="AgentSpace" width="500">
</p>

<p align="center">
  A tiny <b>agent operating system</b> you run from a shell — built from scratch to learn how agents actually work.<br>
  Talk to it in plain English; it orchestrates agents, and <i>writes new tools and whole agents for itself</i> — all from a hand-written, hackable loop (no agent framework).
</p>

---

## ✨ Highlights

- 🗣️ **Just talk to it.** Type a goal in plain English; a built-in **conductor** discovers
  the right agents, delegates, chains them, and synthesizes the answer.
- 🛠️ **Agents write their own tools.** Missing a capability? An agent calls `write_tool`
  and [PI](https://github.com/badlogic/pi-mono) authors it into the registry — usable on
  the next turn.
- 🤖 **The system writes its own agents.** `create-agent "a stock portfolio tracker"`
  (or just ask) and PI builds a whole new agent, live, no restart.
- 🧩 **Everything is hackable & visible.** A hand-written tool-loop (no agent SDK),
  declarative agents (`agent.yaml`), markdown skills, on-disk sessions.
- ⚡ **Parallel & observable.** Each agent is its own process; runs are async with a live
  status feed, plus a separate `agentspace-monitor` console.

## 🎬 Examples

Type these straight into the `agentspace>` prompt:

```text
# orchestration — conductor picks researcher → doc-writer on its own
research france's odds of winning the world cup and make a cool powerpoint about it

# self-writing agent — PI builds it, then you use it
/create-agent a stock portfolio tracking agent
/start stock-portfolio-tracker
/send stock-portfolio-tracker "how would $5k split across NVDA, AAPL, MSFT be doing?"

# self-writing tool — doc-writer has no document tool, so it authors one
/send doc-writer "create a markdown doc 'treehouse.md' with sections Overview, Materials, Steps"

# plain research with citations
what's the latest stable python release? cite a source

# let the conductor figure out it needs a new kind of agent entirely
I want to track my reading list — set that up and add "Dune"
```

> Commands start with `/` (try `/list` to see everything you've got). Anything **without**
> a slash is a natural-language goal handed to the conductor.

---

## Quick start

```bash
export ANTHROPIC_API_KEY=sk-ant-...                 # agents call the Messages API
uv sync                                              # install python deps
npm install -g @mariozechner/pi-coding-agent         # optional: enables write_tool

uv run agentspace                                    # launch the host shell
uv run agentspace-monitor                            # (optional, 2nd terminal) live feed
```

```text
# just say what you want — the conductor discovers and orchestrates the agents:
agentspace> research france's odds of winning the world cup and make a cool powerpoint about it

# …or drive agents directly with /commands:
agentspace> /list
agentspace> /start researcher
agentspace> /send researcher "what's the latest stable python? cite a source"
agentspace> /ps
agentspace> /quit
```

> No API key? The host still runs and you can start/stop agents — the conductor and `send` just return a clear error.

---

## How it works

```text
  HOST (REPL shell)  ──start/stop──▶  agent: researcher   (process · http :7001)
        │                            agent: doc-writer    (process · http :7002)
        └── send ──http POST──────────────▲  each runs its own raw Messages-API loop
```

**The conductor (natural language).** Type a goal in plain English and the host's
conductor (`agentspace/host/orchestrator.py`) plans it: it discovers the registered
agents (`list_agents`), delegates sub-tasks to the best-suited ones (`run_agent`,
auto-starting them), chains their outputs, and synthesizes a final answer — streaming
each step as it goes. For *"research France's WC odds and make a deck"* it routes
`researcher` → `doc-writer` on its own. Explicit commands (`start`, `send`, `ps`, …)
still work for driving agents directly.

**Host (control plane).** Apart from the conductor, the shell launches one OS process
per agent, stops them, and relays messages over HTTP. Agents run in parallel and show
up in `ps`.

**Agent (one process each).** Every agent is a small HTTP server wrapping a
**hand-written tool loop** (`agentspace/agent/loop.py`) against the raw Anthropic
Messages API:

```text
load history → call the model → if it wants a tool, run it and feed the result back → repeat → save
```

That loop is the whole point — nothing is hidden behind an SDK.

**Tools** come in two flavors:
- `web_search` is a **server tool** — Anthropic runs it; we never touch it.
- `sh`, `load_skill`, `write_tool` are **client tools** — we execute them locally.

**Skills** (`skills/<name>/SKILL.md`) are markdown playbooks with progressive
disclosure: the prompt only lists a skill's name + description until the agent calls
`load_skill` to pull in the full instructions.

**Sessions** are conversation history persisted to disk, so an agent remembers across
messages (`send … --session <id>`).

**Async runs + live status.** `send` returns immediately with a run id; a background
monitor streams each step (`🔧 web_search…`, `· thinking…`) and prints the reply when
it's done. Fire several agents and watch them interleave. Long-running tools stream
interim progress too — `write_tool` reports each of PI's steps (`✎ pi: writing
create_document.py …`) instead of going dark for minutes.

**A separate monitor console.** Run `agentspace-monitor` in a second terminal for a
unified, timestamped, color-coded feed of *everything* across all agents — every model
turn, tool call, PI authoring step, and final reply. Read-only; great for watching an
orchestration unfold while you keep typing in the main shell.

**Self-extending (the fun part).** The system can grow itself, at two levels, both via
the [PI](https://github.com/badlogic/pi-mono) coding agent:
- **New tools** — give an agent `write_tool` and it authors the tool it's missing: PI
  writes a module into `agentspace/agent/tools/generated/`, the registry hot-reloads, and
  the agent calls its brand-new tool on the next turn. That's how `doc-writer` ships with
  **no** document tool yet creates one on demand.
- **New agents** — `create-agent <description>` (or just ask the conductor) has PI write a
  whole `agents/<slug>/agent.yaml` from your description, wiring up its prompt, tools, and
  skills. The registry discovers it instantly — no restart. e.g. *"a stock portfolio
  tracking agent"* → a ready-to-run agent that can even author its own quote-fetching tool.

---

## Shell commands

Commands start with `/`. Anything without a slash is a natural-language goal for the conductor.

| command | what it does |
|---|---|
| *(plain English)* | hand a goal to the conductor — it picks & orchestrates agents |
| `/list` | plain-English overview of every agent, tool & skill you have |
| `/agents` | list agents and what each is for |
| `/create-agent <description>` | have PI build a new agent and add it to the registry |
| `/ps` / `/ls` | agent status table (running/stopped, port, pid) |
| `/start` / `/stop` / `/restart <name>` | manage agent processes |
| `/send <name> "<msg>" [--session <id>] [--wait]` | send a message (async; `--wait` blocks) |
| `/status` / `/runs <name>` | in-flight runs / run history |
| `/logs <name> [n]` | tail an agent's log |
| `/sessions <name>` / `/session <name> <id>` | list / inspect sessions |
| `/help` / `/quit` | help / exit |

## Add an agent

Drop a folder under `agents/` — no code change needed:

```yaml
# agents/my-agent/agent.yaml
name: my-agent
model: claude-sonnet-4-6
system_prompt: |
  You are a helpful agent.
tools: [sh, load_skill]      # web_search, sh, load_skill, write_tool
skills: [summarize]
can_author_tools: false      # true to allow write_tool (PI)
```

## Layout

```text
agentspace/host/      host REPL, supervisor, registry  (control plane)
agentspace/agent/     loop, server, sessions, tools, pi_bridge  (one per process)
agents/               declarative agent registry (agent.yaml each)
skills/               markdown skills
docs/TOOL_CONTRACT.md the tool contract (also handed to PI)
```

## Safety

`sh` runs real commands and `write_tool` writes & runs code via PI — both on your
machine, inside the agent's working dir, logged. Great for a local sandbox; don't point
these agents at untrusted input.

## License

[MIT](LICENSE) © 2026 Olivier Meirhaeghe
