"""SSE streaming event schemas."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class StreamEventType(StrEnum):
    START = "start"
    TOKEN = "token"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    AGENT_HANDOFF = "agent_handoff"
    GRAPH_NODE = "graph_node"
    GRAPH_STEP = "graph_step"
    DONE = "done"
    ERROR = "error"
    HEARTBEAT = "heartbeat"


class StreamEvent(BaseModel):
    event: StreamEventType
    data: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None
