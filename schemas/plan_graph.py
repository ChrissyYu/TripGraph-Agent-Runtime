"""Execution DAG graph schemas."""

from enum import StrEnum

from pydantic import BaseModel, Field


class GraphNodeStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class PlanGraphNode(BaseModel):
    id: int
    task: str
    tool_hint: str | None = None
    status: GraphNodeStatus
    error: str | None = None


class PlanGraphEdge(BaseModel):
    """Edge from dependency (source) to dependent step (target)."""

    source: int
    target: int


class PlanExecutionGraphSnapshot(BaseModel):
    goal: str
    session_id: str | None = None
    current_step: int | None = None
    nodes: list[PlanGraphNode] = Field(default_factory=list)
    edges: list[PlanGraphEdge] = Field(default_factory=list)

    def node_map(self) -> dict[int, PlanGraphNode]:
        return {node.id: node for node in self.nodes}
