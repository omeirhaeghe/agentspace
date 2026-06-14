<p align="center">
  <img src="docs/logo.svg" alt="AgentSpace" width="500">
</p>

<p align="center">
  A tiny <b>agent operating system</b> you run from a shell — built from scratch to learn how agents actually work.<br>
  No agent framework: the tool-loop, sessions, process supervision, and even <i>self-written tools</i> are all visible and hackable.
</p>

---

## Quick start

```bash
export ANTHROPIC_API_KEY=sk-ant-...                 # agents call the Messages API
uv sync                                              # install python deps
npm install -g @mariozechner/pi-coding-agent         # optional: enables write_tool

uv run agentspace                                    # launch the host shell
```

```text
# just say what you want — the conductor discovers and orchestrates the agents:
agentspace> research france's odds of winning the world cup and make a cool powerpoint about it

# …or drive agents directly:
agentspace> start researcher
agentspace> send researcher "what's the latest stable python? cite a source"
agentspace> ps
agentspace> quit
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
it's done. Fire several agents and watch them interleave.

**Self-writing tools (the fun part).** Give an agent `write_tool` and it can author the
tool it's missing: it shells out to the [PI](https://github.com/badlogic/pi-mono) coding
agent, which writes a new module into `agentspace/agent/tools/generated/`, the registry
hot-reloads, and the agent calls its brand-new tool on the next turn. That's how
`doc-writer` ships with **no** document tool yet can still create one on demand.

---

## Shell commands

| command | what it does |
|---|---|
| *(plain English)* | hand a goal to the conductor — it picks & orchestrates agents |
| `agents` | list agents and what each is for |
| `do <goal>` / `ask <goal>` | explicitly send a goal to the conductor |
| `ps` / `ls` | list agents and their status |
| `start` / `stop` / `restart <name>` | manage agent processes |
| `send <name> "<msg>" [--session <id>] [--wait]` | send a message (async; `--wait` blocks) |
| `status` / `runs <name>` | in-flight runs / run history |
| `logs <name> [n]` | tail an agent's log |
| `sessions <name>` / `session <name> <id>` | list / inspect sessions |
| `help` / `quit` | help / exit |

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
