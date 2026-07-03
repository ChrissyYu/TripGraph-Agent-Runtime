"""Persistence API schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReplayExecutionRequest(BaseModel):
    execution_id: str = Field(..., min_length=1)
    node_id: str | None = None
    compare_with: str | None = None


class SessionRestoreRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    query: str | None = None


class ExecutionDetailResponse(BaseModel):
    execution_id: str
    session_id: str
    query: str
    status: str
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    state_versions: list[dict[str, Any]] = Field(default_factory=list)
    execution: dict[str, Any] = Field(default_factory=dict)
