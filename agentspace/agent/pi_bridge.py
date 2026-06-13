"""Bridge to the PI coding agent (`pi`) for authoring new tools.

When an agent calls `write_tool`, we shell out to `pi -p` (print / non-interactive
mode) in the repo root, handing it our tool contract as the system prompt and a
spec describing the tool to write. PI uses its own read/write/edit/bash tools to
create `agentspace/agent/tools/generated/<name>.py`.

Docs: https://github.com/badlogic/pi-mono — `pi -p` runs autonomously and exits.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from agentspace.common import paths

PI_TIMEOUT_SECONDS = 240
_VALID_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def _rel(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def author_tool(root: Path, name: str, description: str, spec: str) -> tuple[bool, str]:
    """Drive PI to write a new tool module. Returns (ok, message)."""
    if not _VALID_NAME.match(name):
        return False, (
            f"ERROR: invalid tool name '{name}'. Use snake_case starting with a "
            "letter (e.g. create_document)."
        )

    pi = shutil.which("pi")
    if not pi:
        return False, (
            "ERROR: the `pi` binary is not installed. Run "
            "`npm install -g @mariozechner/pi-coding-agent` to enable write_tool."
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
        "Write ONLY that one file. Do not modify any other file. After writing it, "
        "double-check it imports cleanly and follows the contract."
    )

    # pi defaults to the Google provider; steer it to Anthropic (overridable).
    provider = os.environ.get("AGENTSPACE_PI_PROVIDER", "anthropic")
    model = os.environ.get("AGENTSPACE_PI_MODEL")

    cmd = [
        pi,
        "-p",
        "--no-session",
        "--provider",
        provider,
        "-t",
        "read,write,edit,bash",
    ]
    if model:
        cmd += ["--model", model]
    if contract:
        cmd += ["--append-system-prompt", contract]
    cmd.append(prompt)

    print(f"[write_tool] invoking pi to author '{name}' -> {target_rel}", flush=True)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=PI_TIMEOUT_SECONDS,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        return False, f"ERROR: pi timed out after {PI_TIMEOUT_SECONDS}s while authoring '{name}'."
    except Exception as exc:  # noqa: BLE001
        return False, f"ERROR: failed to run pi: {exc}"

    pi_out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if len(pi_out) > 4000:
        pi_out = pi_out[-4000:]

    if not target.exists():
        return False, (
            f"ERROR: pi finished (exit {proc.returncode}) but {target_rel} was not "
            f"created.\n--- pi output ---\n{pi_out}"
        )

    return True, (
        f"✓ Authored tool '{name}' at {target_rel} (pi exit {proc.returncode}). "
        "The tool registry has been reloaded; the tool is now callable."
    )
