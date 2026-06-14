# One image that can run any AgentSpace agent as a web service.
# Includes Node (npx) and uv (uvx) so MCP servers work in the cloud too.
FROM python:3.13-slim

# Node for npx-based MCP servers; git for the git MCP server.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# uv (and uvx) for Python deps and uvx-based MCP servers.
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY . /app

# Install project + deps into /app/.venv and put it on PATH.
RUN uv sync --frozen || uv sync
ENV PATH="/app/.venv/bin:$PATH"

# Persist sessions/logs on a mounted disk (see render.yaml).
ENV AGENTSPACE_RUNTIME_DIR=/data/runtime

EXPOSE 8000
# Which agent to run is chosen at deploy time via AGENTSPACE_AGENT.
CMD ["agentspace-serve"]
