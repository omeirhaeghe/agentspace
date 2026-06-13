"""The `write_tool` meta-tool: let an agent author a brand-new tool via PI.

Gated by the agent's `can_author_tools` flag (enforced in the registry — this
module is only assembled into the toolset when the flag is set). On success the
agent loop re-scans `tools/generated/` so the new tool is callable immediately.
"""

from __future__ import annotations

from agentspace.agent import pi_bridge

SCHEMA = {
    "name": "write_tool",
    "description": (
        "Author a NEW tool for yourself when you lack a capability. Describe the "
        "tool and an implementation spec; the PI coding agent writes it and it "
        "becomes callable on your next turn. Use this when no existing tool can do "
        "what the user asked (e.g. creating a document, making a chart)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "snake_case tool name, e.g. create_document.",
            },
            "description": {
                "type": "string",
                "description": "One sentence: what the tool does (the model-facing description).",
            },
            "spec": {
                "type": "string",
                "description": (
                    "Detailed spec: the inputs (names + types), the behavior, and "
                    "what string it returns. Be concrete."
                ),
            },
        },
        "required": ["name", "description", "spec"],
    },
}


def handler(ctx, name: str, description: str, spec: str) -> str:
    ok, message = pi_bridge.author_tool(ctx.root, name, description, spec)
    return message
