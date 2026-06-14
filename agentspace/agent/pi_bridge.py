"""Bridge to the PI coding agent (`pi`) for authoring tools and agents.

We shell out to `pi -p` (print / non-interactive mode) in the repo root, handing it a
contract as its system prompt and a task describing what to write. PI uses its own
read/write/edit/bash tools to create the files, then exits.

`run_pi()` is the shared primitive (streams output, enforces a timeout). `author_tool()`
uses it to write a new tool module; `agentspace/host/agent_factory.py` uses it to write
a new agent.

Docs: https://github.com/badlogic/pi-mono
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

from agentspace.common import paths

PI_TIMEOUT_SECONDS = 240
_VALID_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def _rel(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def run_pi(root: Path, prompt: str, system_append: str | None = None,
           tools: str = "read,write,edit,bash", progress=None) -> dict:
    """Run `pi -p` with a prompt and stream its output. Returns a result dict:
    {ok, returncode, output, timed_out, error}. `progress(text)` (optional) gets each
    output line live."""
    progress = progress or (lambda text: None)

    pi = shutil.which("pi")
    if not pi:
        return {
            "ok": False,
            "error": "the `pi` binary is not installed. Run "
            "`npm install -g @mariozechner/pi-coding-agent`.",
            "output": "",
            "returncode": None,
            "timed_out": False,
        }

    # pi defaults to the Google provider; steer it to Anthropic (overridable).
    provider = os.environ.get("AGENTSPACE_PI_PROVIDER", "anthropic")
    model = os.environ.get("AGENTSPACE_PI_MODEL")

    cmd = [pi, "-p", "--no-session", "--provider", provider, "-t", tools]
    if model:
        cmd += ["--model", model]
    if system_append:
        cmd += ["--append-system-prompt", system_append]
    cmd.append(prompt)

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=os.environ.copy(),
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"failed to run pi: {exc}", "output": "",
                "returncode": None, "timed_out": False}

    timed_out = {"v": False}

    def _kill():
        timed_out["v"] = True
        proc.kill()

    timer = threading.Timer(PI_TIMEOUT_SECONDS, _kill)
    timer.start()
    lines: list[str] = []
    try:
        for raw in proc.stdout:  # streams as pi prints
            line = raw.rstrip()
            if line:
                lines.append(line)
                progress(f"pi: {line[:120]}")
    finally:
        proc.wait()
        timer.cancel()

    return {
        "ok": not timed_out["v"] and proc.returncode == 0,
        "error": "pi timed out" if timed_out["v"] else None,
        "output": "\n".join(lines).strip()[-4000:],
        "returncode": proc.returncode,
        "timed_out": timed_out["v"],
    }


def author_tool(root: Path, name: str, description: str, spec: str, progress=None) -> tuple[bool, str]:
    """Drive PI to write a new tool module. Returns (ok, message)."""
    progress = progress or (lambda text: None)
    if not _VALID_NAME.match(name):
        return False, (
            f"ERROR: invalid tool name '{name}'. Use snake_case starting with a "
            "letter (e.g. create_document)."
        )

    contract_path = paths.tool_contract_path(root)
    contract = contract_path.read_text() if contract_path.exists() else ""

    target = paths.generated_tools_dir() / f"{name}.py"
    target_rel = _rel(root, target)

    prompt = (
        f"Write a new AgentSpace tool to the file `{target_rel}` (create it; "
        "overwrite if it exists).\n\n"
        f"Tool name: {name}\n"
        f"Purpose: {description}\n\n"
        f"Specification:\n{spec}\n\n"
        "The module MUST expose a `SCHEMA` dict and a `handler(ctx, **input)` "
        "function exactly as described in the system prompt (the tool contract). "
        "Write ONLY that one file. Do not modify any other file."
    )

    print(f"[write_tool] invoking pi to author '{name}' -> {target_rel}", flush=True)
    progress(f"pi: authoring {name} → {target_rel}")
    res = run_pi(root, prompt, system_append=contract, progress=progress)
    if not res["ok"]:
        return False, f"ERROR: {res.get('error') or 'pi failed'} (authoring '{name}')."

    if not target.exists():
        return False, (
            f"ERROR: pi finished (exit {res['returncode']}) but {target_rel} was not "
            f"created.\n--- pi output ---\n{res['output']}"
        )

    progress(f"pi: done — {target_rel} written")
    return True, (
        f"✓ Authored tool '{name}' at {target_rel} (pi exit {res['returncode']}). "
        "The tool registry has been reloaded; the tool is now callable."
    )
