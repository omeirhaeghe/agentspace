# AgentSpace

A tiny **agent operating system** you run from a shell — built from scratch to learn how
agents actually work. No high-level agent SDK: the tool-use loop, sessions, tool dispatch,
and process supervision are all visible and hackable.

```
HOST (REPL shell)  ──spawn/kill──>  agent: researcher  (uvicorn :7001)  raw Messages loop
       │                            agent: shell-helper (uvicorn :7002)  raw Messages loop
       └──HTTP POST /responses─────────────^
```

- **Host** — an interactive shell (`agentspace>`) that starts/stops agents and sends them
  messages. It is a control plane only; it never calls the model.
- **Agents** — each runs as its own OS process exposing a Responses-style HTTP API
  (`POST /responses`). They run in parallel and are visible in `ps`.
- **Tools** — `web_search` (Anthropic server tool), `sh` (local shell), `load_skill`,
  and `write_tool` (writes *new* tools via the [PI](https://github.com/badlogic/pi-mono)
  coding agent — agents that extend themselves).
- **Skills** — markdown playbooks in `skills/`, loaded on demand (progressive disclosure).
- **Sessions** — per-agent conversation history persisted to disk.

## Setup

```bash
export ANTHROPIC_API_KEY=sk-ant-...                 # agents use the raw Messages API
uv sync                                              # install python deps
npm install -g @mariozechner/pi-coding-agent         # the `pi` binary (for write_tool)
```

> Without the key the shell still starts but warns, and `send` returns a clear error.
> Without `pi`, only `write_tool` fails — everything else works.

## Run

```bash
uv run agentspace
```

Then in the shell:

```
agentspace> ps
agentspace> start researcher
agentspace> send researcher "What is the latest stable Python release? cite a source"
agentspace> start doc-writer
agentspace> send doc-writer "Create a markdown doc 'treehouse.md' with sections Overview, Materials, Steps"
agentspace> logs doc-writer
agentspace> stop researcher
agentspace> quit
```

### Shell commands
| command | description |
|---------|-------------|
| `ps` / `ls` | list registered agents + status (running/stopped, port, pid) |
| `start <name>` / `stop <name>` / `restart <name>` | manage agent processes |
| `send <name> "<msg>" [--session <id>] [--wait]` | send a message — **async**: returns a run id immediately and streams status; `--wait` blocks until done |
| `status` | show in-flight runs being tracked |
| `runs <name>` | list an agent's recent runs |
| `logs <name> [n]` | tail the agent's server log |
| `sessions <name>` / `session <name> <id>` | list / inspect sessions |
| `help` / `quit` | help / exit (offers to stop running agents) |

### Async runs & live status

`send` does not block. It starts the turn inside the agent process and returns a
`run_id`; you keep the prompt. A background monitor streams each step as it happens
and prints the reply when the run finishes:

```
agentspace> send researcher "latest stable python? cite a source"
→ researcher run run_ab12 started (session 9f3c…). status streams below.
agentspace>   [researcher·run_ab12] → received: latest stable python? cite a source
  [researcher·run_ab12] · turn 1: thinking…
  [researcher·run_ab12] 🔧 web_search(query='latest stable python release')
  [researcher·run_ab12] ✓ web_search → …
  [researcher·run_ab12] · turn 2: thinking…

researcher> Python 3.x.y is the latest stable release … [source](https://…)
  [session 9f3c… · 2 turns · 1 tool calls · 1234in/567out tokens]
```

Because runs are async you can fire several agents at once and watch them interleave;
`status` shows what's in flight. Use `send … --wait` for scripts that want the reply inline.

## Add an agent

Drop a folder under `agents/`:

```yaml
# agents/my-agent/agent.yaml
name: my-agent
model: claude-sonnet-4-6
system_prompt: |
  You are a helpful agent.
tools: [sh, load_skill]
skills: [summarize]
max_tokens: 4096
can_author_tools: false    # set true to allow write_tool (PI)
```

No code change needed — `ps` will show it immediately.

## Add a skill

Create `skills/<name>/SKILL.md` with front-matter (`name`, `description`) and a body of
instructions. Agents that list the skill see only its name+description until they call
`load_skill`, which returns the full body.

## How an agent writes its own tool (PI)

Give an agent `write_tool` + `can_author_tools: true`. When it lacks a capability it calls
`write_tool(name, description, spec)`; AgentSpace runs `pi -p` with
[`docs/TOOL_CONTRACT.md`](docs/TOOL_CONTRACT.md) as the system prompt, PI writes
`agentspace/agent/tools/generated/<name>.py`, the registry hot-reloads, and the new tool is
callable on the agent's next turn. See `agents/doc-writer/` for the demo.

## Safety note

The `sh` tool runs real shell commands on your machine (inside the agent's working dir, with a
timeout, logged). That's intentional for a local sandbox — don't expose these agents to
untrusted input. `write_tool` likewise lets a model write+run code via PI.

## Layout

```
agentspace/host/      # REPL shell, supervisor, registry (control plane)
agentspace/agent/     # loop, server, sessions, tools, pi_bridge (the agent process)
agents/               # declarative agent registry (agent.yaml per agent)
skills/               # markdown skills
docs/TOOL_CONTRACT.md # the tool module contract (also fed to PI)
runtime/              # gitignored: pids, ports, logs, sessions
```
