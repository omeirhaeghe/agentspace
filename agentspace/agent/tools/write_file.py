"""The `write_file` tool: write a text file into the agent's output directory."""

from __future__ import annotations

SCHEMA = {
    "name": "write_file",
    "description": "Write a UTF-8 text file. The file is created under the agent's output "
    "directory; pass a filename or a relative subpath (no '..').",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "e.g. 'notes.md' or 'sub/report.txt'."},
            "content": {"type": "string", "description": "The file contents."},
        },
        "required": ["filename", "content"],
    },
}


def handler(ctx, filename: str, content: str) -> str:
    if ".." in filename.split("/"):
        return "ERROR: filename may not contain '..'"
    path = (ctx.output_dir / filename).resolve()
    if not str(path).startswith(str(ctx.output_dir.resolve())):
        return "ERROR: filename must stay within the output directory"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return f"Wrote {path} ({len(content)} chars)"
