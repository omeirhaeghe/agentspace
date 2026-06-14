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

from agentspace.common import paths
from agentspace.host import remotes

API = "https://api.render.com/v1"
POLL_TIMEOUT = 600
PASSTHROUGH_ENV = ("ANTHROPIC_API_KEY", "AGENTSPACE_TOKEN", "GITHUB_TOKEN")


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


def _env_vars(agent: str) -> list[dict]:
    out = [{"key": "AGENTSPACE_AGENT", "value": agent}]
    for k in PASSTHROUGH_ENV:
        v = os.environ.get(k)
        if v:
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
                    "envVars": _env_vars(agent),
                }
                r = client.post(f"{API}/services", json=payload)
                if r.status_code >= 300:
                    return False, f"Render create failed ({r.status_code}): {r.text}", None
                created = r.json()
                service = created.get("service", created)
                service_id = service["id"]

            # Make sure env vars are current, then trigger a deploy.
            client.put(f"{API}/services/{service_id}/env-vars", json=_env_vars(agent))
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
