"""Replay and debug utilities for graph runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from graph.runtime.agent_state import AgentState
from graph.runtime.execution_policy import ExecutionPolicy
from schemas.execution_graph import ExecutionGraphModel, NodeExecutionRecord
from schemas.plan import ExecutionTraceEntry

if TYPE_CHECKING:
    from graph.runtime.runner import GraphRuntimeRunner


@dataclass
class ReplayStep:
    node_id: str
    sequence: int
    input_state_hash: str
    output_state_hash: str
    input_state: dict[str, Any] | None
    output_state: dict[str, Any] | None
    state_delta: dict[str, Any]
    replayed: bool


@dataclass
class DebugSession:
    """Debug session with pause / inspect support."""

    paused_at: str | None = None
    paused_snapshot: dict[str, Any] | None = None
    _continue: bool = True

    async def pause_hook(self, node_id: str, snapshot: dict[str, Any]) -> None:
        self.paused_at = node_id
        self.paused_snapshot = snapshot
        self._continue = False

    def inspect(self) -> dict[str, Any]:
        return {
            "paused_at": self.paused_at,
            "snapshot": self.paused_snapshot,
        }

    def resume(self) -> None:
        self._continue = True

    @property
    def should_continue(self) -> bool:
        return self._continue


class GraphReplayDebugger:
    """Replay graph execution from structured trace or execution_trace."""

    def __init__(self, runner: GraphRuntimeRunner) -> None:
        self._runner = runner

    @staticmethod
    def from_execution_trace(
        execution_trace: list[ExecutionTraceEntry],
        *,
        graph_id: str = "replay_from_execution_trace",
        session_id: str = "replay",
    ) -> ExecutionGraphModel:
        records: list[NodeExecutionRecord] = []
        for index, entry in enumerate(execution_trace):
            records.append(
                NodeExecutionRecord(
                    node_id=f"plan_step_{entry.step_id}",
                    sequence=index,
                    input_state_hash=f"trace_in_{entry.step_id}",
                    output_state_hash=f"trace_out_{entry.step_id}",
                    state_delta={
                        "task": entry.task,
                        "status": entry.status.value,
                        "tool_name": entry.tool_name,
                        "success": entry.success,
                    },
                    status="completed" if entry.success else "failed",
                ),
            )
        return ExecutionGraphModel(
            graph_id=graph_id,
            session_id=session_id,
            mode="replay",
            node_records=records,
        )

    async def replay_all(
        self,
        execution_graph: ExecutionGraphModel,
        *,
        initial_state: AgentState | None = None,
    ) -> AsyncIterator[ReplayStep]:
        policy = ExecutionPolicy().with_replay(execution_graph)
        policy.capture_state_snapshots = True

        state = initial_state or AgentState(
            session_id=execution_graph.session_id,
            query=execution_graph.session_id,
        )
        state.execution_graph = execution_graph

        graph = self._runner.workflow
        async for event in graph.astream(state, policy=policy):
            if event.get("type") != "node_end":
                continue
            record = self._find_record(execution_graph, event["sequence"])
            yield ReplayStep(
                node_id=event["node_id"],
                sequence=event["sequence"],
                input_state_hash=event["input_state_hash"],
                output_state_hash=event["output_state_hash"],
                input_state=record.input_state_snapshot if record else None,
                output_state=record.output_state_snapshot if record else None,
                state_delta=event.get("state_delta", {}),
                replayed=event.get("replayed", False),
            )

    async def replay_node(
        self,
        execution_graph: ExecutionGraphModel,
        node_id: str,
        *,
        initial_state: AgentState | None = None,
    ) -> ReplayStep | None:
        async for step in self.replay_all(execution_graph, initial_state=initial_state):
            if step.node_id == node_id:
                return step
        return None

    def inspect_node(
        self,
        execution_graph: ExecutionGraphModel,
        node_id: str,
        *,
        phase: str = "output",
    ) -> dict[str, Any] | None:
        for record in execution_graph.node_records:
            if record.node_id != node_id:
                continue
            if phase == "input":
                return record.input_state_snapshot
            if phase == "output":
                return record.output_state_snapshot
            return {
                "input_state_hash": record.input_state_hash,
                "output_state_hash": record.output_state_hash,
                "state_delta": record.state_delta,
                "input": record.input_state_snapshot,
                "output": record.output_state_snapshot,
            }
        return None

    async def debug_invoke(
        self,
        query: str,
        *,
        session_id: str = "debug",
        pause_at: set[str] | None = None,
    ) -> tuple[AgentState, DebugSession]:
        session = DebugSession()
        policy = ExecutionPolicy().with_debug(
            pause_at=pause_at or set(),
            hook=session.pause_hook,
        )
        policy.capture_state_snapshots = True

        state = AgentState(session_id=session_id, query=query)
        state.append_message("user", query)
        graph = self._runner.workflow

        current_state = state
        async for event in graph.astream(state, policy=policy):
            if event.get("type") == "state":
                current_state = event["state"]
            if not session.should_continue:
                break

        return current_state, session

    @staticmethod
    def _find_record(
        execution_graph: ExecutionGraphModel,
        sequence: int,
    ) -> NodeExecutionRecord | None:
        for record in execution_graph.node_records:
            if record.sequence == sequence:
                return record
        return None
