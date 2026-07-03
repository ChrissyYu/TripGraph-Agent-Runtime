"""Unified global state for graph-native runtime."""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel, Field

from plan.state import PlanState
from schemas.execution_critic import ExecutionCritique
from schemas.execution_graph import ExecutionGraphModel
from schemas.graph_runtime import GraphTraceEntry
from schemas.plan import ExecutionTraceEntry, Plan
from schemas.replanning import ReplanningResult
from schemas.state_versioning import StateVersionStore


class AgentState(BaseModel):
    """Single global state mutated by graph nodes."""

    messages: list[dict[str, Any]] = Field(default_factory=list)
    plan: Plan | None = None
    current_step: int | None = None
    observations: dict[str, Any] = Field(default_factory=dict)
    execution_trace: list[ExecutionTraceEntry] = Field(default_factory=list)
    graph_trace: list[GraphTraceEntry] = Field(default_factory=list)
    memory: dict[str, Any] = Field(default_factory=dict)

    short_term_memory: list[dict[str, Any]] = Field(default_factory=list)
    long_term_memory: list[dict[str, Any]] = Field(default_factory=list)
    episodic_memory: list[dict[str, Any]] = Field(default_factory=list)

    execution_graph: ExecutionGraphModel | None = None
    version_store: StateVersionStore | None = None
    state_version_id: str | None = None
    branch_id: str = "main"
    parent_graph_id: str | None = None
    nested_graph_id: str | None = None

    # Runtime control fields
    session_id: str = "default"
    query: str = ""
    plan_state: PlanState | None = None
    final_result: str | None = None
    execution_critique: ExecutionCritique | None = None
    replan_history: list[ReplanningResult] = Field(default_factory=list)
    should_stop: bool = False
    replan_attempts: int = 0
    execution_seed: int | None = None

    model_config = {"arbitrary_types_allowed": True}

    def append_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def log_graph(self, node_id: str, event: str, **data: Any) -> None:
        self.graph_trace.append(
            GraphTraceEntry(
                node_id=node_id,
                event=event,
                data=data,
                step_index=len(self.graph_trace),
            ),
        )

    def snapshot(self) -> dict[str, Any]:
        from graph.runtime.state_hash import state_to_serializable

        return state_to_serializable(self)

    def apply_snapshot(self, snapshot: dict[str, Any]) -> AgentState:
        merged = self.model_dump()
        for key, value in snapshot.items():
            if key in ("plan_state", "execution_graph"):
                continue
            merged[key] = copy.deepcopy(value)
        if "version_store" in snapshot and snapshot["version_store"]:
            merged["version_store"] = StateVersionStore.model_validate(snapshot["version_store"])
        return AgentState.model_validate(merged)

    def api_snapshot(self) -> dict[str, Any]:
        """Serializable snapshot for API round-trip including version history."""
        snap = self.snapshot()
        if self.version_store:
            snap["version_store"] = self.version_store.model_dump(mode="json")
        return snap

    @classmethod
    def from_api_snapshot(cls, snapshot: dict[str, Any]) -> AgentState:
        skip = {"version_store", "plan_state", "execution_graph"}
        data = {k: v for k, v in snapshot.items() if k in cls.model_fields and k not in skip}
        state = cls.model_validate(data)
        if snapshot.get("version_store"):
            state.version_store = StateVersionStore.model_validate(snapshot["version_store"])
        return state

    def summary(self) -> dict[str, Any]:
        base = {
            "session_id": self.session_id,
            "query": self.query,
            "current_step": self.current_step,
            "plan_goal": self.plan.goal if self.plan else None,
            "graph_steps": len(self.graph_trace),
            "execution_trace_count": len(self.execution_trace),
            "replan_attempts": self.replan_attempts,
            "should_stop": self.should_stop,
            "short_term_memory_count": len(self.short_term_memory),
            "long_term_memory_count": len(self.long_term_memory),
            "episodic_memory_count": len(self.episodic_memory),
            "execution_seed": self.execution_seed,
            "state_version_id": self.state_version_id,
            "branch_id": self.branch_id,
        }
        if self.version_store:
            base["version_count"] = len(self.version_store.versions)
        if self.plan_state:
            base.update(self.plan_state.summary())
        if self.execution_graph:
            base["execution_graph_nodes"] = len(self.execution_graph.node_records)
        if self.observations.get("plan_repair_notes"):
            base["plan_repair_notes"] = self.observations["plan_repair_notes"]
        if self.observations.get("tool_policy_trace"):
            base["tool_policy_trace"] = self.observations["tool_policy_trace"]
        if self.observations.get("tool_policy_counters"):
            base["tool_policy_counters"] = self.observations["tool_policy_counters"]
        return base
