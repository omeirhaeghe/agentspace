# Rust rewrite plan (parked — future work)

> Status: **designed, not started.** Captured so it survives. Optimize for instant startup,
> one binary, and agent density — NOT response latency (turns are model-bound, identical in
> any language).

## Context
Today each agent is its own Python+uvicorn **OS process** (~1–2 s cold start, ~40–70 MB each)
reached over HTTP. Goal: a single native **`agentspace`** binary that starts instantly, has a
tiny footprint, and runs many agents at once.

**Key architectural shift:** agents stop being OS processes behind HTTP and become
**in-process async tasks** (tokio) that talk to the TUI over channels. No per-process cold
start, ~KB per agent, and the per-agent panes + input can finally live in one full-screen TUI.

**Reused as-is:** the declarative registry is language-agnostic — Rust reads the same
`agents/<name>/agent.yaml`, `skills/<name>/SKILL.md`, `mcp/servers.yaml`, and the
`runtime/<agent>/sessions/*.json` format → Rust and Python run side-by-side during migration.

## Stack
Single Cargo binary (`rust/` workspace): **tokio**, **reqwest**+rustls, raw **Anthropic
Messages API** client (keeps the from-scratch tool loop), **rmcp** v0.16 (official MCP Rust
SDK, tokio-native), **ratatui**+crossterm (TUI), **serde** / serde_yaml / serde_json,
**clap**. Prereq: install Rust via `rustup` (arm64 mac → native binary, `cargo build --release`).

## Architecture (in-process, channel-driven)
```
agentspace (one binary, one process)
 ├─ tui (ratatui)      input box + per-agent panes + scrollback + history
 ├─ runtime            registry; start = spawn tokio task, stop = abort
 │   └─ agent task ×N  each runs the loop; streams events over an mpsc channel
 ├─ conductor          orchestration (in-process run_agent via channels)
 └─ shared: anthropic · tools · mcp · skills · sessions · settings · pricing
```
Module map mirrors today's Python: `config` (serde_yaml ↔ agent.yaml / servers.yaml /
settings.json), `anthropic` (messages.create + tool_use/usage), `agent` (tool loop + event
channel, port of `loop.py`), `tools` (a `Tool` trait: `schema()` + `async call(ctx,input)`;
sh/read_file/write_file/http_fetch/python/load_skill), `mcp` (rmcp client manager), `skills`,
`sessions` (same JSON format), `conductor`, `runtime` (task supervisor), `tui`, `pricing`.
Blocking work (sh/python) → `tokio::process` / `spawn_blocking`.

## Phasing
- **Phase 1 — fast local MVP:** config, anthropic client, agent loop, core tools, sessions,
  skills, settings, pricing, ratatui (input + panes + history); agents as in-process tasks;
  start/stop/send/ps/list. → instant start, one binary, density.
- **Phase 2 — parity:** MCP via rmcp; web_search (server tool); the conductor.
- **Phase 3 — optional:** remote mode (axum HTTP + bearer auth) + Render deploy; `write_tool`.

## Known wrinkle: self-writing tools
`write_tool` today hot-loads a PI-authored **Python** module — impossible for compiled Rust at
runtime. Redesign: PI writes a **script** (python/sh) + JSON tool-spec into `tools/generated/`,
run by a generic `run_generated(name, args)` executor. Same UX, different mechanism (Phase 3).

## Risks / notes
- Effort is weeks (hence phases); Phase 1 alone gives the headline wins.
- Latency unchanged (model-bound); SSE streaming later makes tokens *appear* sooner.
- Trade OS-process isolation for task isolation (catch panics per `JoinHandle`); sh/python/MCP
  still run as child processes.
- Use rustls (no OpenSSL) so the binary is self-contained.

## Verification
1. `rustup` install; `cargo build --release` → single `target/release/agentspace`.
2. Measure: `hyperfine` startup; agent-start time vs Python (ms vs ~1–2 s).
3. Density: start 20 agents; compare RSS (1 Rust process vs 20 Python).
4. Parity: point at existing `agents/researcher`; `send` → streamed events + a session saved
   in the same `runtime/.../sessions/*.json` Python uses.
5. Side-by-side: a Rust agent and a Python agent against the same `agents/` dir.
