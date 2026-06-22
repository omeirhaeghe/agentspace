"""Deploy an agent to Render via the REST API (https://render.com/docs/api).

`/deploy <agent>` calls create_or_deploy(): create (or reuse) a Docker web service from
this GitHub repo, set its env vars (model key, auth token, which agent), trigger a build,
poll until live, and record {url, service_id} in deploys.yaml so the host can reach it.

Needs RENDER_API_KEY and AGENTSPACE_TOKEN in the environment. If Render rejects the
create payload (the API schema occasionally shifts), the error body is surfaced verbatim —
the render.yaml Blueprint is the guaranteed fallback (see docs/DEPLOY.md).
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import httpx

from agentspace.agent.config import AgentSpec
from agentspace.common import paths
from agentspace.host import remotes
from agentspace.host import settings as host_settings

API = "https://api.render.com/v1"
POLL_TIMEOUT = 600
# Host env vars forwarded verbatim to the deployed service when present.
PASSTHROUGH_ENV = ("ANTHROPIC_API_KEY", "AGENTSPACE_TOKEN", "GITHUB_TOKEN", "SLACK_WEBHOOK_URL")

# Tools/capabilities that don't carry over to a Render container the way they do on the
# host. Used both to warn at deploy time and to keep that warning honest.
SCHEDULE_TOOLS = {"schedule_create", "schedule_list", "schedule_cancel"}
LOCAL_FS_TOOLS = {"sh", "python", "read_file", "write_file"}
LOCAL_FS_MCP = {"filesystem", "git"}


def _headers() -> dict:
    key = os.environ.get("RENDER_API_KEY")
    if not key:
        raise RuntimeError("RENDER_API_KEY is not set.")
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


def _repo_url(root: Path) -> str:
    if os.environ.get("AGENTSPACE_REPO"):
        return os.environ["AGENTSPACE_REPO"]
    try:
        url = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        url = ""
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url[len("git@github.com:"):]
    return url.removesuffix(".git")


def _owner_id(client: httpx.Client) -> str:
    r = client.get(f"{API}/owners", params={"limit": 1})
    r.raise_for_status()
    data = r.json()
    return data[0]["owner"]["id"]


def _find_service(client: httpx.Client, name: str) -> dict | None:
    r = client.get(f"{API}/services", params={"name": name, "limit": 1})
    r.raise_for_status()
    items = r.json()
    return items[0]["service"] if items else None


def _notify_env(root: Path) -> dict[str, str]:
    """Telegram creds to forward so a cloud agent's send_notification can reach a phone.

    Prefer the environment; fall back to the host's settings.json (where `/setup` stores
    them). Slack rides along via PASSTHROUGH_ENV (SLACK_WEBHOOK_URL).
    """
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    cid = os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and cid):
        s = host_settings.load(root)
        tok = tok or s.telegram_bot_token
        cid = cid or s.telegram_chat_id
    if tok and cid:
        return {"TELEGRAM_BOT_TOKEN": tok, "TELEGRAM_CHAT_ID": cid}
    return {}


def _has_notify_creds(root: Path) -> bool:
    return bool(os.environ.get("SLACK_WEBHOOK_URL")) or bool(_notify_env(root))


def cloud_warnings(spec: AgentSpec, *, notify_creds: bool) -> list[str]:
    """Human-readable notes on which of this agent's tools degrade in the cloud."""
    tools = set(spec.tools)
    warns: list[str] = []
    if tools & SCHEDULE_TOOLS:
        warns.append(
            "schedule_* — scheduling runs host-side; a cloud agent writes jobs the host "
            "ticker never fires."
        )
    if "send_notification" in tools and not notify_creds:
        warns.append(
            "send_notification — no Telegram/Slack creds to forward and desktop is "
            "macOS-only; alerts fall back to log-only. Run /setup (or set "
            "TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID / SLACK_WEBHOOK_URL), then redeploy."
        )
    if spec.can_author_tools or "write_tool" in tools:
        warns.append(
            "write_tool / PI — pi-coding-agent isn't in the image and authored files are "
            "ephemeral; self-authoring won't work in the cloud."
        )
    if (tools & LOCAL_FS_TOOLS) or (set(spec.mcp_servers) & LOCAL_FS_MCP):
        warns.append(
            "sh / python / file tools and the filesystem & git MCP servers act on the "
            "container's repo snapshot, not your Mac's live files."
        )
    return warns


def _env_vars(root: Path, agent: str) -> list[dict]:
    out = [{"key": "AGENTSPACE_AGENT", "value": agent}]
    for k in PASSTHROUGH_ENV:
        v = os.environ.get(k)
        if v:
            out.append({"key": k, "value": v})
    for k, v in _notify_env(root).items():
        out.append({"key": k, "value": v})
    return out


def create_or_deploy(root: Path, agent: str, plan: str = "starter", progress=None) -> tuple[bool, str, dict | None]:
    progress = progress or (lambda t: None)

    if not os.environ.get("RENDER_API_KEY"):
        return False, "RENDER_API_KEY is not set. export it (Render dashboard → Account → API Keys).", None
    if not os.environ.get("AGENTSPACE_TOKEN"):
        return False, "AGENTSPACE_TOKEN is not set — remote agents MUST be auth-protected. Set one first.", None
    cfg = paths.agents_dir(root) / agent / "agent.yaml"
    if not cfg.is_file():
        return False, f"no such agent: {agent}", None

    # Surface tools that won't behave the same on Render *before* the long build.
    try:
        warns = cloud_warnings(AgentSpec.from_yaml(cfg), notify_creds=_has_notify_creds(root))
    except Exception:  # noqa: BLE001 — never block a deploy on the advisory check
        warns = []
    if warns:
        progress("⚠ heads-up — some of this agent's tools degrade in the cloud:")
        for w in warns:
            progress(f"  - {w}")

    repo = _repo_url(root)
    if "github.com" not in repo:
        return False, "could not determine a GitHub repo URL (set AGENTSPACE_REPO).", None

    service_name = f"agentspace-{agent}"
    try:
        with httpx.Client(headers=_headers(), timeout=30) as client:
            existing = _find_service(client, service_name)
            if existing:
                service_id = existing["id"]
                progress(f"reusing service {service_name} ({service_id})")
            else:
                progress(f"creating service {service_name} from {repo}")
                payload = {
                    "type": "web_service",
                    "name": service_name,
                    "ownerId": _owner_id(client),
                    "repo": repo,
                    "branch": "main",
                    "autoDeploy": "yes",
                    "serviceDetails": {
                        "env": "docker",
                        "plan": plan,
                        "healthCheckPath": "/health",
                        "envSpecificDetails": {"dockerfilePath": "./Dockerfile", "dockerContext": "."},
                        "disk": {"name": f"{service_name}-data", "mountPath": "/data", "sizeGB": 1},
                    },
                    "envVars": _env_vars(root, agent),
                }
                r = client.post(f"{API}/services", json=payload)
                if r.status_code >= 300:
                    return False, f"Render create failed ({r.status_code}): {r.text}", None
                created = r.json()
                service = created.get("service", created)
                service_id = service["id"]

            # Make sure env vars are current, then trigger a deploy.
            client.put(f"{API}/services/{service_id}/env-vars", json=_env_vars(root, agent))
            progress("triggering deploy…")
            r = client.post(f"{API}/services/{service_id}/deploys", json={})
            if r.status_code >= 300:
                return False, f"Render deploy failed ({r.status_code}): {r.text}", None
            deploy_id = r.json().get("id", "")

            ok = _poll(client, service_id, deploy_id, progress)
            svc = client.get(f"{API}/services/{service_id}").json()
            svc = svc.get("service", svc)
            url = (svc.get("serviceDetails") or {}).get("url") or f"https://{service_name}.onrender.com"

        info = {"url": url, "service_id": service_id, "provider": "render"}
        remotes.put(root, agent, info)
        if ok:
            return True, f"✓ {agent} live at {url}", info
        return True, f"{agent} deploy started; {url} (still building — check Render).", info
    except httpx.HTTPError as exc:
        return False, f"Render API error: {exc}", None
    except RuntimeError as exc:
        return False, str(exc), None


def _poll(client: httpx.Client, service_id: str, deploy_id: str, progress) -> bool:
    if not deploy_id:
        return False
    deadline = time.monotonic() + POLL_TIMEOUT
    last = None
    while time.monotonic() < deadline:
        r = client.get(f"{API}/services/{service_id}/deploys/{deploy_id}")
        if r.status_code < 300:
            status = (r.json().get("deploy") or r.json()).get("status", "?")
            if status != last:
                progress(f"build: {status}")
                last = status
            if status in ("live",):
                return True
            if status in ("build_failed", "update_failed", "canceled", "deactivated", "failed"):
                return False
        time.sleep(5)
    return False


def delete(root: Path, agent: str, progress=None) -> tuple[bool, str]:
    progress = progress or (lambda t: None)
    info = remotes.get(root, agent)
    if not info:
        return False, f"{agent} is not deployed."
    try:
        with httpx.Client(headers=_headers(), timeout=30) as client:
            r = client.delete(f"{API}/services/{info['service_id']}")
            if r.status_code >= 300 and r.status_code != 404:
                return False, f"Render delete failed ({r.status_code}): {r.text}"
    except (httpx.HTTPError, RuntimeError) as exc:
        return False, f"Render API error: {exc}"
    remotes.remove(root, agent)
    return True, f"✓ removed {agent} ({info['url']})"
