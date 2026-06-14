"""Create whole agents from a natural-language description, via PI.

`write_tool` lets an agent author a *tool*; this authors a whole *agent*. We hand PI
the agent contract and the description; PI writes `agents/<slug>/agent.yaml` (and, if the
agent needs them, starter tools). Because the registry scans `agents/` on every call, the
new agent is immediately visible to `ps` / `agents` / the conductor — no restart.
"""

from __future__ import annotations

from pathlib import Path

from agentspace.agent import pi_bridge
from agentspace.agent.config import AgentSpec
from agentspace.agent.tools import registry as tool_registry
from agentspace.common import paths
from agentspace.host import registry


def _agent_names(root: Path) -> set[str]:
    return {p.name for p in paths.agents_dir(root).iterdir()
            if (p / "agent.yaml").is_file()} if paths.agents_dir(root).is_dir() else set()


def create_agent(root: Path, description: str, progress=None) -> tuple[bool, str, str | None]:
    """Drive PI to create a new agent. Returns (ok, message, agent_name)."""
    progress = progress or (lambda text: None)
    description = (description or "").strip()
    if not description:
        return False, "ERROR: please describe the agent to create.", None

    contract_path = paths.agent_contract_path(root)
    contract = contract_path.read_text() if contract_path.exists() else ""

    skills = sorted(p.name for p in paths.skills_dir(root).iterdir()
                    if (p / "SKILL.md").is_file()) if paths.skills_dir(root).is_dir() else []
    before = _agent_names(root)

    prompt = (
        "Create a new AgentSpace agent from this description:\n\n"
        f"    {description}\n\n"
        f"Available skills: {', '.join(skills) or '(none)'}\n"
        f"Existing agents (do NOT overwrite these): {', '.join(sorted(before)) or '(none)'}\n\n"
        "Choose a short kebab-case slug and write `agents/<slug>/agent.yaml` exactly as "
        "described in the system prompt (the agent contract). If the agent needs a "
        "capability no built-in tool covers, prefer giving it write_tool + "
        "can_author_tools so it can author the tool itself later."
    )

    progress(f"pi: designing agent for “{description[:60]}”")
    res = pi_bridge.run_pi(root, prompt, system_append=contract, progress=progress)
    if not res["ok"]:
        return False, f"ERROR: {res.get('error') or 'pi failed'} while creating the agent.", None

    after = _agent_names(root)
    new = sorted(after - before)
    if not new:
        return False, (
            f"ERROR: pi finished (exit {res['returncode']}) but no new agent appeared.\n"
            f"--- pi output ---\n{res['output']}"
        ), None
    if len(new) > 1:
        progress(f"pi: created multiple agents: {', '.join(new)}")

    name = new[0]
    cfg = registry.config_path(root, name)
    try:
        spec = AgentSpec.from_yaml(cfg)
    except Exception as exc:  # noqa: BLE001
        return False, f"ERROR: created '{name}' but its agent.yaml is invalid: {exc}", name

    # Validate the tools it references actually exist (warn, don't fail).
    known = set(tool_registry.SERVER_TOOLS) | set(tool_registry.discover()) | {"write_tool"}
    unknown = [t for t in spec.tools if t not in known]
    warn = f" (note: references unknown tools {unknown})" if unknown else ""

    progress(f"pi: done — agent '{name}' created")
    return True, (
        f"✓ Created agent '{name}' — {spec.description or 'no description'}{warn}. "
        f"It's in the registry now; `start {name}` then `send {name} \"…\"`."
    ), name
