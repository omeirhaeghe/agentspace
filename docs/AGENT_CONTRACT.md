# AgentSpace Agent Contract

You are creating a new **agent** for AgentSpace. An agent is a folder under `agents/`
containing a single `agent.yaml`. The runtime auto-discovers it — no code changes.

Write the file to `agents/<slug>/agent.yaml`, where `<slug>` is a short kebab-case name
you derive from the description (e.g. "stock-portfolio-tracker"). Do not overwrite an
existing agent.

## agent.yaml schema

```yaml
name: <slug>                 # MUST equal the folder name
model: claude-sonnet-4-6     # use this default unless there is a clear reason not to
description: <one line>      # what the agent is for — the conductor uses this to route tasks
system_prompt: |             # the agent's instructions; be specific about its job, style, and limits
  You are ...
tools: [ ... ]               # subset of the available tools below
skills: [ ... ]              # optional subset of available skills
can_author_tools: false      # set true if the agent should be allowed to write its own tools
max_tokens: 4096
```

## Available built-in tools (choose what the agent needs)
- `web_search` — search the web (current data, research, prices, news)
- `sh` — run shell commands on the host machine
- `load_skill` — load a skill's full instructions on demand
- `write_tool` — author NEW tools at runtime (only works if `can_author_tools: true`)

## Available skills
Listed in the task message. Reference them by name in `skills:` if relevant.

## Giving the agent real, domain-specific capabilities
If the agent needs something no built-in tool provides (e.g. fetching stock quotes),
choose ONE:

1. **Lazy (preferred, simplest):** set `can_author_tools: true` and include `write_tool`
   in `tools`. The agent writes the tool itself the first time it needs it. Tell it to do
   so in its `system_prompt` (e.g. "if you lack a tool to fetch quotes, author one with
   write_tool").
2. **Eager:** author the tool now — create `agentspace/agent/tools/generated/<tool>.py`
   following `docs/TOOL_CONTRACT.md`, and list its `name` in the agent's `tools`. Only do
   this when the tool is essential and simple.

## Rules
- Write valid YAML. The agent must load (fields above; unknown keys are rejected).
- Keep the agent focused and give it a precise, useful `system_prompt`.
- Write exactly one `agent.yaml` (plus tool files only if you chose option 2).
- Prefer a small, sensible `tools` list over enabling everything.
