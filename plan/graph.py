"""Plan execution DAG for debug and visualization."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from schemas.plan import Plan, PlanStep, StepStatus
from schemas.plan_graph import (
    GraphNodeStatus,
    PlanExecutionGraphSnapshot,
    PlanGraphEdge,
    PlanGraphNode,
)

if TYPE_CHECKING:
    from plan.state import PlanState


class PlanExecutionGraph:
    """DAG view of plan steps and dependencies with live execution status."""

    def __init__(self, plan: Plan, *, session_id: str = "default") -> None:
        self._goal = plan.goal
        self._session_id = session_id
        self._steps: dict[int, PlanStep] = {step.id: step for step in plan.steps}
        self._status: dict[int, GraphNodeStatus] = {
            step.id: GraphNodeStatus.PENDING for step in plan.steps
        }
        self._errors: dict[int, str | None] = {step.id: None for step in plan.steps}
        self._edges: list[PlanGraphEdge] = self._build_edges(plan.steps)
        self._current_step: int | None = None

    @classmethod
    def from_plan(cls, plan: Plan, *, session_id: str = "default") -> PlanExecutionGraph:
        return cls(plan, session_id=session_id)

    @property
    def current_step(self) -> int | None:
        return self._current_step

    def sync_from_state(self, state: PlanState) -> None:
        """Refresh node statuses from PlanState."""
        self._goal = state.plan.goal
        self._session_id = state.session_id
        self._current_step = state.current_step

        self._steps = {step.id: step for step in state.plan.steps}
        self._edges = self._build_edges(state.plan.steps)

        for step_id in list(self._status.keys()):
            if step_id not in self._steps:
                self._status.pop(step_id, None)
                self._errors.pop(step_id, None)

        for step in state.plan.steps:
            if step.id not in self._status:
                self._status[step.id] = GraphNodeStatus.PENDING
                self._errors[step.id] = None

            step_status = state.get_step_status(step.id)
            self._status[step.id] = self._map_status(step_status)
            result = state.step_results.get(step.id)
            self._errors[step.id] = result.error if result else None

    def set_node_status(
        self,
        step_id: int,
        status: GraphNodeStatus,
        *,
        error: str | None = None,
    ) -> None:
        if step_id not in self._steps:
            raise KeyError(f"Unknown graph node: {step_id}")
        self._status[step_id] = status
        if error is not None:
            self._errors[step_id] = error

    def set_current_step(self, step_id: int | None) -> None:
        self._current_step = step_id

    def rebuild_from_plan(self, plan: Plan) -> None:
        """Rebuild graph topology after replanning."""
        self._steps = {step.id: step for step in plan.steps}
        self._edges = self._build_edges(plan.steps)
        for step in plan.steps:
            if step.id not in self._status:
                self._status[step.id] = GraphNodeStatus.PENDING
                self._errors[step.id] = None

    def get_graph_snapshot(self) -> PlanExecutionGraphSnapshot:
        nodes = [
            PlanGraphNode(
                id=step.id,
                task=step.task,
                tool_hint=step.tool_hint,
                status=self._status[step.id],
                error=self._errors.get(step.id),
            )
            for step in sorted(self._steps.values(), key=lambda s: s.id)
        ]
        return PlanExecutionGraphSnapshot(
            goal=self._goal,
            session_id=self._session_id,
            current_step=self._current_step,
            nodes=nodes,
            edges=list(self._edges),
        )

    def export_graph_json(self, *, indent: int = 2) -> str:
        snapshot = self.get_graph_snapshot()
        if indent is None:
            return json.dumps(snapshot.model_dump(), ensure_ascii=False)
        return json.dumps(snapshot.model_dump(), ensure_ascii=False, indent=indent)

    def export_graph_dict(self) -> dict:
        return self.get_graph_snapshot().model_dump()

    @staticmethod
    def _build_edges(steps: list[PlanStep]) -> list[PlanGraphEdge]:
        edges: list[PlanGraphEdge] = []
        for step in steps:
            for dep in step.dependency or []:
                edges.append(PlanGraphEdge(source=dep, target=step.id))
        return edges

    @staticmethod
    def _map_status(status: StepStatus) -> GraphNodeStatus:
        mapping = {
            StepStatus.PENDING: GraphNodeStatus.PENDING,
            StepStatus.RUNNING: GraphNodeStatus.RUNNING,
            StepStatus.COMPLETED: GraphNodeStatus.SUCCESS,
            StepStatus.FAILED: GraphNodeStatus.FAILED,
            StepStatus.SKIPPED: GraphNodeStatus.SUCCESS,
        }
        return mapping[status]
