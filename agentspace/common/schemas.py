"""Pydantic models shared between the agent HTTP API and the host client.

The request/response shape intentionally mirrors a minimal slice of the OpenAI
Responses API: you POST an `input` (plus an optional `session_id` for
statefulness) and get back the assistant output along with the session id to
continue from.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ResponsesRequest(BaseModel):
    """Body of `POST /responses`."""

    input: str = Field(..., description="The user message to send to the agent.")
    session_id: str | None = Field(
        default=None,
        description="Continue an existing session. If omitted, a new one is created.",
    )


class ResponsesResponse(BaseModel):
    """Result of `POST /responses`."""

    id: str = Field(..., description="Unique id for this response.")
    session_id: str = Field(..., description="Session this turn belongs to.")
    output_text: str = Field(..., description="Concatenated assistant text.")
    output: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Raw content blocks of the final assistant message.",
    )
    usage: dict[str, Any] = Field(
        default_factory=dict, description="Token usage / tool-call counters."
    )


class HealthResponse(BaseModel):
    """Result of `GET /health`."""

    name: str
    status: str = "ok"
    model: str
    tools: list[str] = Field(default_factory=list)
