# MCP servers in AgentSpace

Agents can use tools from [Model Context Protocol](https://modelcontextprotocol.io)
servers — the same ecosystem Claude Desktop / Claude Code use. An MCP server's tools show
up to an agent as normal tools, named `mcp__<server>__<tool>`.

## How it fits together

```
agents/<name>/agent.yaml   mcp_servers: [filesystem, fetch]
         │ references by name
         ▼
mcp/servers.yaml           the catalog: how to launch/reach each server
         │
         ▼
MCPManager (per agent)     connects, lists tools, bridges async↔sync,
                           merges them into the agent's toolset
```

Each agent process connects to the servers it lists, at startup, and reuses the
connections across turns. A server that fails to start is logged and skipped — the rest of
the agent still works.

## Declaring a server (`mcp/servers.yaml`)

Two transports:

```yaml
servers:
  # stdio: a local subprocess
  filesystem:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
    env: { SOME_VAR: value }        # optional, merged over the process env

  # remote: a hosted server over streamable HTTP
  acme:
    url: "https://mcp.acme.com/"
    headers: { Authorization: "Bearer ${ACME_TOKEN}" }
    enabled: true                   # set false to keep it defined but skipped
```

`${ENV_VAR}` is expanded anywhere from the environment — keep tokens out of the file.

## Giving an agent MCP tools

Add the server name(s) to the agent's `mcp_servers:`:

```yaml
# agents/files/agent.yaml
name: files
mcp_servers: [filesystem]
tools: [sh, load_skill]
```

Then `/start files` and `/mcp` to see the live connection, or `/send files "find and read
paths.py"` and watch the `mcp__filesystem__*` calls in the feed / `agentspace-monitor`.

## Prerequisites

- **stdio servers** need their launcher on PATH: `npx` (Node) for `@modelcontextprotocol/*`
  packages, `uvx` (uv) for Python `mcp-server-*` packages. Both are bundled in this repo's
  toolchain.
- **github** (in the default catalog) is `enabled: false` until you `export GITHUB_TOKEN=…`
  and flip it on.

## Bundled example servers

| server | transport | auth | tools (examples) |
|--------|-----------|------|------------------|
| filesystem | stdio (`npx`) | none | read_file, list_directory, search_files, write_file |
| fetch | stdio (`uvx`) | none | fetch(url) → markdown |
| git | stdio (`uvx`) | none | git_status, git_diff, git_log |
| github | remote http | `GITHUB_TOKEN` | issues, PRs, code search |

## Notes & limits

- Each agent process spawns its **own** copy of a stdio server it uses (process isolation).
- First launch of an `npx`/`uvx` server downloads the package — the first connect is slower.
- Tool results are returned as text (image/binary content is summarized, not embedded).
