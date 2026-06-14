# AgentSpace Tool Contract

Every AgentSpace tool is a single Python module that exposes exactly two top-level
names. The tool registry (`agentspace/agent/tools/registry.py`) auto-discovers any
module in `agentspace/agent/tools/` or `agentspace/agent/tools/generated/` that
follows this contract. PI-authored tools MUST follow it too.

## 1. `SCHEMA` — an Anthropic tool definition (a dict)

```python
SCHEMA = {
    "name": "create_document",                # snake_case, matches the module's purpose
    "description": "Write a markdown document with a title and sections to disk.",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "e.g. 'brief.md'"},
            "title": {"type": "string"},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["heading", "body"],
                },
            },
        },
        "required": ["filename", "title", "sections"],
    },
}
```

- `name` must be unique across all tools and a valid identifier.
- `description` is what the model sees — be precise about what the tool does.
- `input_schema` is standard JSON Schema (`type: object` at the top).

## 2. `handler(ctx, **input) -> str`

```python
def handler(ctx, **input):
    # ctx gives you the runtime context (see below). input is the validated
    # tool input as keyword args matching input_schema's properties.
    ...
    return "human-readable result string"   # ALWAYS return a str
```

- The first positional parameter is always `ctx` (a `ToolContext`).
- Remaining arguments arrive as keyword args named exactly as in `input_schema`.
- Return a **string** (the tool_result sent back to the model). Summaries/paths are great.
- On error, return a string starting with `ERROR:` — do not raise; raising is caught
  and reported, but a clean message is better.

### `ctx` (ToolContext) fields
| field | type | meaning |
|-------|------|---------|
| `ctx.root` | `pathlib.Path` | AgentSpace repo root |
| `ctx.workdir` | `pathlib.Path` | working dir for file/command ops (defaults to repo root) |
| `ctx.output_dir` | `pathlib.Path` | **where to write any artifacts the tool produces** |
| `ctx.skills_dir` | `pathlib.Path` | the `skills/` directory |
| `ctx.allowed_skills` | `list[str]` | skills this agent may load |
| `ctx.agent_name` | `str` | the calling agent's name |

### Writing output files (IMPORTANT)
If your tool produces a file (a document, image, deck, export, …), write it under
`ctx.output_dir` — never to the repo root or the current working directory. Resolve a
user-supplied filename against it and create the dir first:

```python
ctx.output_dir.mkdir(parents=True, exist_ok=True)
path = ctx.output_dir / filename        # filename like "report.pptx"
```

Return the path you wrote so the caller can find it.

## Full minimal example

```python
from pathlib import Path

SCHEMA = {
    "name": "create_document",
    "description": "Write a markdown document with a title and sections to disk.",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
            "title": {"type": "string"},
            "sections": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["filename", "title", "sections"],
    },
}


def handler(ctx, filename, title, sections):
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    path = ctx.output_dir / filename
    lines = [f"# {title}", ""]
    for s in sections:
        lines.append(f"## {s['heading']}")
        lines.append(s.get("body", ""))
        lines.append("")
    path.write_text("\n".join(lines))
    return f"Wrote {path} ({path.stat().st_size} bytes)"
```

## Rules for PI when authoring a tool
1. Write ONE module at the exact path you are told (under `tools/generated/`).
2. Expose `SCHEMA` and `handler` exactly as above. No other side effects at import time.
3. Use only the Python standard library unless told otherwise. If a shell tool helps
   (e.g. `pdftotext`), call it via `subprocess` inside `handler`, not at import time.
4. Keep `handler` synchronous and fast; always return a concise string.
5. Do not modify any other file.
