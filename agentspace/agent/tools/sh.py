"""The `sh` tool: run a shell command on the host.

Client-executed. Runs inside the agent's working directory with a timeout and
captures (does not stream) stdout+stderr. Every command is printed so it lands in
the agent's server.log.
"""

from __future__ import annotations

import subprocess

TIMEOUT_SECONDS = 60
MAX_OUTPUT_CHARS = 16000

SCHEMA = {
    "name": "sh",
    "description": (
        "Run a shell command on the host machine and return its combined "
        "stdout+stderr. Runs in the agent's working directory with a "
        f"{TIMEOUT_SECONDS}s timeout. Use for listing files, running scripts, "
        "git, etc."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute (run via /bin/sh -c).",
            }
        },
        "required": ["command"],
    },
}


def handler(ctx, command: str) -> str:
    print(f"[sh] $ {command}", flush=True)
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(ctx.workdir),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {TIMEOUT_SECONDS}s"
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: failed to run command: {exc}"

    out = (proc.stdout or "") + (proc.stderr or "")
    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS] + f"\n…[truncated {len(out) - MAX_OUTPUT_CHARS} chars]"
    return f"(exit {proc.returncode})\n{out}".rstrip()
