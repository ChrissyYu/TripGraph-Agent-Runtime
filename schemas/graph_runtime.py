"""Phase 4 graph runtime API schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from schemas.execution_critic import ExecutionCritique
from schemas.plan import ExecutionTraceEntry, Plan
from schemas.replanning import ReplanningResult


class GraphTraceEntry(BaseModel):
    node_id: str
    event: str
    data: dict[str, Any] = Field(default_factory=dict)
    step_index: int = 0


class NodeTimelineEntry(BaseModel):
    node_id: str
    started_at_step: int
    ended_at_step: int
    duration_steps: int = 1
    status: str = "completed"
    detail: dict[str, Any] = Field(default_factory=dict)


class GraphExecuteRequest(BaseModel):
    session_id: str = Field(default="default", min_length=1)
    query: str = Field(..., min_length=1)
    stream: bool = False
    seed: int | None = None
    deterministic: bool = False
    debug: bool = False
    pause_at_nodes: list[str] = Field(default_factory=list)
    merge_strategy: str | None = None


class GraphReplayRequest(BaseModel):
    session_id: str = Field(default="default", min_length=1)
    execution_graph: dict[str, Any]
    node_id: str | None = None


class GraphExecuteResponse(BaseModel):
    session_id: str
    plan: Plan | None = None
    graph_trace: list[GraphTraceEntry]
    execution_trace: list[ExecutionTraceEntry]
    node_timeline: list[NodeTimelineEntry]
    final_result: str
    execution_critique: ExecutionCritique | None = None
    replan_history: list[ReplanningResult] = Field(default_factory=list)
    state_summary: dict[str, Any] = Field(default_factory=dict)
    runtime: str = "graph"
    execution_graph: dict[str, Any] | None = None
    execution_graph_mermaid: str | None = None
    execution_graph_dot: str | None = None
    execution_seed: int | None = None
    state_version_id: str | None = None
    version_summary: dict[str, Any] | None = None
    execution_id: str | None = None


class StateRollbackRequest(BaseModel):
    session_id: str = Field(default="default", min_length=1)
    version_id: str
    state_snapshot: dict[str, Any]


class StateForkRequest(BaseModel):
    session_id: str = Field(default="default", min_length=1)
    from_version_id: str | None = None
    branch_name: str | None = None
    state_snapshot: dict[str, Any]


class StateDiffRequest(BaseModel):
    version_a: str
    version_b: str
    state_snapshot: dict[str, Any]


class StateBranchReplayRequest(BaseModel):
    session_id: str = Field(default="default", min_length=1)
    query: str = Field(..., min_length=1)
    from_version_id: str
    branch_name: str | None = None
    state_snapshot: dict[str, Any]
