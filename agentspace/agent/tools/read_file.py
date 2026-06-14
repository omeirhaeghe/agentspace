"""The `read_file` tool: read a text file from the agent's working directory."""

from __future__ import annotations

from pathlib import Path

MAX_BYTES = 100_000

SCHEMA = {
    "name": "read_file",
    "description": "Read a UTF-8 text file and return its contents. Relative paths resolve "
    "against the agent's working directory.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path (relative or absolute)."}
        },
        "required": ["path"],
    },
}


def handler(ctx, path: str) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = ctx.workdir / p
    if not p.exists():
        return f"ERROR: no such file: {p}"
    if not p.is_file():
        return f"ERROR: not a file: {p}"
    try:
        data = p.read_bytes()[:MAX_BYTES]
        text = data.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: could not read {p}: {exc}"
    note = "" if p.stat().st_size <= MAX_BYTES else f"\n…[truncated to {MAX_BYTES} bytes]"
    return text + note
