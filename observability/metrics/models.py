"""Metrics domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class MetricEventType(StrEnum):
    GRAPH_START = "graph_start"
    GRAPH_END = "graph_end"
    NODE_START = "node_start"
    NODE_END = "node_end"
    TOOL_CALL = "tool_call"
    LLM_CALL = "llm_call"
    ERROR = "error"


class NodeMetric(BaseModel):
    node_id: str
    sequence: int = 0
    latency_ms: float = 0.0
    status: str = "completed"


class ToolMetric(BaseModel):
    call_id: str
    tool_name: str
    latency_ms: float = 0.0
    success: bool = True
    attempt: int = 1
    max_attempts: int = 1
    is_retry: bool = False
    is_fallback: bool = False
    error: str | None = None


class LLMMetric(BaseModel):
    caller: str
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    estimated: bool = False
    model: str | None = None
    provider: str | None = None


class ExecutionMetrics(BaseModel):
    execution_id: str
    session_id: str
    trace_id: str
    query: str = ""
    graph_id: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    graph_execution_time_ms: float | None = None
    status: str = "running"
    nodes: list[NodeMetric] = Field(default_factory=list)
    tools: list[ToolMetric] = Field(default_factory=list)
    llm_calls: list[LLMMetric] = Field(default_factory=list)
    retry_count: int = 0

    @property
    def tool_success_rate(self) -> float:
        if not self.tools:
            return 1.0
        successes = sum(1 for tool in self.tools if tool.success)
        return successes / len(self.tools)

    @property
    def total_llm_tokens(self) -> int:
        return sum(call.total_tokens for call in self.llm_calls)

    @property
    def total_estimated_cost_usd(self) -> float:
        return sum(call.estimated_cost_usd for call in self.llm_calls)
