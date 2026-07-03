"""Agent-related domain schemas."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AgentRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    MANAGER = "manager"
    SPECIALIST = "specialist"


class AgentMessage(BaseModel):
    role: AgentRole
    content: str
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentTask(BaseModel):
    task_id: str
    session_id: str
    query: str
    target_specialist: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class AgentTaskResult(BaseModel):
    task_id: str
    session_id: str
    output: str
    specialist_used: str | None = None
    tool_calls: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentLoopResult(BaseModel):
    """Result of a completed agent tool-calling loop."""

    session_id: str
    final_answer: str
    messages: list[AgentMessage] = Field(default_factory=list)
    tool_call_order: list[str] = Field(default_factory=list)
    iterations: int = 0
    terminated: bool = False
