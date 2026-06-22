# Deploying agents to the cloud (Render)

An agent is already an HTTP service, so hosting one remotely just means running the same
server on [Render](https://render.com) and pointing the host at its URL. You keep driving
it exactly like a local agent — `/send`, the conductor, and `agentspace-monitor` all work
against the remote URL.

> ⚠️ **Security:** remote agents run `sh` / `python` / MCP. A public endpoint MUST be
> locked down. AgentSpace enforces a bearer token: when `AGENTSPACE_TOKEN` is set the agent
> rejects any request without `Authorization: Bearer <token>`. `/deploy` refuses to run
> without a token. Never commit secrets — they live in Render env vars.

## One-time setup
```bash
export RENDER_API_KEY=rnd_…       # Render dashboard → Account Settings → API Keys
export AGENTSPACE_TOKEN=$(openssl rand -hex 24)   # shared bearer token for your remote agents
export ANTHROPIC_API_KEY=sk-ant-…  # forwarded to the deployed agent
# optional: export GITHUB_TOKEN=… to enable the github MCP server remotely
# optional: Telegram/Slack creds are forwarded too, so a deployed watchdog can reach your
#           phone. /setup already stores Telegram creds; or set them explicitly:
#   export TELEGRAM_BOT_TOKEN=…  TELEGRAM_CHAT_ID=…
#   export SLACK_WEBHOOK_URL=…
```
Keep the same `AGENTSPACE_TOKEN` in your host shell (so it can authenticate) as is set on
the services (deploy sets it for you).

## Deploy from the tool
```text
agentspace> /deploy coder
☁  deploying coder to Render…
  · creating service agentspace-coder from https://github.com/you/agentspace
  · build: build_in_progress
  · build: live
✓ coder live at https://agentspace-coder.onrender.com

agentspace> /deploys                       # list remote agents + status
agentspace> /send coder "refactor X"       # works exactly like a local agent
agentspace> /ps                            # LOCATION shows the remote host
agentspace> /undeploy coder                # tear it down
```

`/deploy` builds the `Dockerfile` (Python + Node + uv, so MCP works in the cloud), mounts a
1 GB disk at `/data` for persistent sessions, sets the env vars, and polls until live. The
resulting URL is saved to `deploys.yaml` (gitignored, no secrets) so the host can route to it.

## How it works
- **Image:** one `Dockerfile` runs any agent; `AGENTSPACE_AGENT=<name>` (an env var) picks
  which one, and the platform's `$PORT` is bound on `0.0.0.0` (`agentspace-serve`).
- **Routing:** the supervisor returns a remote base URL + bearer header for deployed agents,
  a local `127.0.0.1:<port>` otherwise. Everything above it is unchanged.
- **State:** sessions persist on the mounted disk (`AGENTSPACE_RUNTIME_DIR=/data/runtime`).

## What runs in the cloud (and what doesn't)

A deployed agent runs the **same** tool loop as a local one — there's no cloud-only tool
filter — so it gets exactly the tools its `agent.yaml` lists. The image provides the
runtimes those need (Python, Node/npx, uv/uvx, git), but a few capabilities are inherently
host- or Mac-bound. `/deploy` prints a `⚠ heads-up` listing any that apply to the agent
you're deploying, *before* the build starts.

| Capability | In the cloud |
|---|---|
| `web_search`, `web_fetch`, `http_fetch`, `image_search`, `fetch_sports_data` | ✅ work (outbound HTTP / server-side) |
| `fetch` MCP | ✅ runtime installed |
| `filesystem` / `git` MCP | ⚠️ work, but act on the container's repo snapshot, not your Mac |
| `github` MCP | ✅ with `GITHUB_TOKEN` forwarded |
| `sh`, `python`, `read_file`, `write_file` | ⚠️ run against the container, not your laptop |
| `conversation_search`, `recent_chats` | ✅ over the container's own session history (on the disk) |
| `send_notification` → Telegram / Slack | ✅ **only if** creds are forwarded (env or `/setup`); else log-only |
| `send_notification` → desktop | ❌ macOS-only; no-op on Linux |
| `schedule_create` / `schedule_list` / `schedule_cancel` | ❌ the scheduler ticker is host-side; jobs are written but never fire |
| `write_tool` / `can_author_tools` (PI) | ❌ pi-coding-agent isn't in the image and writes are ephemeral |

**Rule of thumb:** deploy **stateless, outward-facing** agents (researcher, translator, an
HTTP/fetch tool agent). Keep **scheduling, watching, and self-authoring** on the host. The
one cross-over that *does* work remotely is a `watchdog` pushing to your phone — as long as
Telegram/Slack creds are forwarded (see setup above).

## Manual / Blueprint alternative (no API key)
Prefer git-push deploys? Use `render.yaml`: in Render, "New → Blueprint", point it at your
repo, set the `sync: false` secrets (`ANTHROPIC_API_KEY`, `AGENTSPACE_TOKEN`) in the
dashboard, and deploy. Duplicate the service block per agent (change `name` +
`AGENTSPACE_AGENT`). Then add the resulting URL to `deploys.yaml` so the host can reach it.

## Notes
- **Cold starts / cost:** the `free` plan spins down when idle (~30 s first-call lag); use
  `starter`+ to stay warm. (`/deploy` uses `starter` by default.)
- **Semantics & capability gaps:** see [What runs in the cloud](#what-runs-in-the-cloud-and-what-doesnt)
  above — remote `sh`/`python`/filesystem act on the container, and a few tools (scheduling,
  notifications, self-authoring) need host-side support that the container doesn't have.
- **If Render rejects the create payload** (its API schema occasionally shifts), the error
  body is printed verbatim — adjust `agentspace/host/deploy.py`, or use the Blueprint path.
- **Vercel** isn't supported for these agents (serverless can't host the long-running,
  stateful, MCP-subprocess loop).
