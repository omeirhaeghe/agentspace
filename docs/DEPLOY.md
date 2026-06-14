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

## Manual / Blueprint alternative (no API key)
Prefer git-push deploys? Use `render.yaml`: in Render, "New → Blueprint", point it at your
repo, set the `sync: false` secrets (`ANTHROPIC_API_KEY`, `AGENTSPACE_TOKEN`) in the
dashboard, and deploy. Duplicate the service block per agent (change `name` +
`AGENTSPACE_AGENT`). Then add the resulting URL to `deploys.yaml` so the host can reach it.

## Notes
- **Cold starts / cost:** the `free` plan spins down when idle (~30 s first-call lag); use
  `starter`+ to stay warm. (`/deploy` uses `starter` by default.)
- **Semantics:** remote `sh` / `python` / filesystem-MCP act on the **container**, not your
  laptop.
- **If Render rejects the create payload** (its API schema occasionally shifts), the error
  body is printed verbatim — adjust `agentspace/host/deploy.py`, or use the Blueprint path.
- **Vercel** isn't supported for these agents (serverless can't host the long-running,
  stateful, MCP-subprocess loop).
