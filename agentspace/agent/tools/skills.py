"""The `load_skill` tool plus skill-catalog helpers.

Skills live in `skills/<name>/SKILL.md` with YAML front-matter (`name`,
`description`) followed by the instruction body. Progressive disclosure: the
agent's system prompt lists only each skill's name + description; the full body is
returned only when the model calls `load_skill`.
"""

from __future__ import annotations

from pathlib import Path

import yaml

SCHEMA = {
    "name": "load_skill",
    "description": (
        "Load the full instructions for one of your available skills by name. "
        "Call this before doing a task the skill covers."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The skill name to load."}
        },
        "required": ["name"],
    },
}


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split '---\\nyaml\\n---\\nbody' into (meta, body)."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                meta = {}
            return meta, parts[2].lstrip("\n")
    return {}, text


def _skill_file(skills_dir: Path, name: str) -> Path:
    return skills_dir / name / "SKILL.md"


def skill_description(skills_dir: Path, name: str) -> str:
    path = _skill_file(skills_dir, name)
    if not path.exists():
        return "(missing SKILL.md)"
    meta, _ = parse_frontmatter(path.read_text())
    return str(meta.get("description", "")).strip() or "(no description)"


def skills_catalog(skills_dir: Path, allowed: list[str]) -> str:
    """Render the name+description list injected into the system prompt."""
    if not allowed:
        return ""
    lines = [
        "",
        "## Skills",
        "You can load these skills with the `load_skill` tool to get detailed "
        "instructions. Only the name and a one-line description are shown here:",
    ]
    for name in allowed:
        lines.append(f"- {name}: {skill_description(skills_dir, name)}")
    return "\n".join(lines)


def handler(ctx, name: str) -> str:
    if name not in ctx.allowed_skills:
        available = ", ".join(ctx.allowed_skills) or "(none)"
        return f"ERROR: skill '{name}' is not available. Available skills: {available}"
    path = _skill_file(ctx.skills_dir, name)
    if not path.exists():
        return f"ERROR: skill file not found: {path}"
    print(f"[load_skill] {name}", flush=True)
    _, body = parse_frontmatter(path.read_text())
    return body or "(skill body is empty)"
