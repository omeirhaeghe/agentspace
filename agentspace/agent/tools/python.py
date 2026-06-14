"""The `python` tool: run a short Python snippet and capture its output.

Runs in a subprocess with a timeout, in the agent's working directory. This executes
real code on the host — intentional for a local sandbox; don't expose to untrusted input.
"""

from __future__ import annotations

import subprocess
import sys

TIMEOUT = 30
MAX_OUTPUT = 16_000

SCHEMA = {
    "name": "python",
    "description": "Run a Python 3 snippet and return its stdout+stderr. Use print() to "
    "emit results. Runs in a subprocess with a timeout; the standard library is available.",
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python source to execute."}
        },
        "required": ["code"],
    },
}


def handler(ctx, code: str) -> str:
    print("[python] running snippet", flush=True)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(ctx.workdir),
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: snippet timed out after {TIMEOUT}s"
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: failed to run snippet: {exc}"
    out = (proc.stdout or "") + (proc.stderr or "")
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + f"\n…[truncated {len(out) - MAX_OUTPUT} chars]"
    return f"(exit {proc.returncode})\n{out}".rstrip()
