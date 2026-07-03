"""Graph runtime service facade."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from graph.runtime.agent_state import AgentState
from graph.runtime.execution_policy import ExecutionPolicy
from graph.runtime.runner import GraphRuntimeRunner
from schemas.execution_graph import ExecutionGraphModel
from schemas.graph_runtime import GraphExecuteRequest, GraphExecuteResponse
from schemas.streaming import StreamEvent


class GraphService:
    def __init__(self, runner: GraphRuntimeRunner) -> None:
        self._runner = runner

    @staticmethod
    def build_policy(body: GraphExecuteRequest) -> ExecutionPolicy:
        policy = ExecutionPolicy(capture_state_snapshots=body.debug or body.deterministic)
        if body.seed is not None:
            policy.with_seed(body.seed)
        elif body.deterministic:
            policy.with_seed(42)
        if body.debug:
            policy.with_debug(pause_at=set(body.pause_at_nodes))
        return policy

    async def execute(self, body: GraphExecuteRequest) -> GraphExecuteResponse:
        return await self._runner.invoke(
            body.query,
            session_id=body.session_id,
            policy=self.build_policy(body),
            merge_strategy=body.merge_strategy,
        )

    def stream(self, body: GraphExecuteRequest) -> AsyncIterator[StreamEvent]:
        return self._runner.stream(
            body.query,
            session_id=body.session_id,
            policy=self.build_policy(body),
            merge_strategy=body.merge_strategy,
        )

    async def replay_node(self, execution_graph: dict, node_id: str) -> dict[str, Any]:
        graph = ExecutionGraphModel.from_dag_json(execution_graph)
        step = await self._runner.debugger.replay_node(graph, node_id)
        if step is None:
            raise KeyError(f"Node not found: {node_id}")
        return {
            "node_id": step.node_id,
            "input_state_hash": step.input_state_hash,
            "output_state_hash": step.output_state_hash,
            "input_state": step.input_state,
            "output_state": step.output_state,
            "state_delta": step.state_delta,
            "replayed": step.replayed,
        }

    async def replay_all(self, execution_graph: dict, *, session_id: str) -> dict[str, Any]:
        graph = ExecutionGraphModel.from_dag_json(execution_graph)
        steps = [step async for step in self._runner.debugger.replay_all(graph)]
        return {
            "session_id": session_id,
            "steps": [
                {
                    "node_id": step.node_id,
                    "sequence": step.sequence,
                    "input_state_hash": step.input_state_hash,
                    "output_state_hash": step.output_state_hash,
                    "replayed": step.replayed,
                }
                for step in steps
            ],
        }

    def inspect_node(
        self,
        execution_graph: dict,
        node_id: str,
        *,
        phase: str = "output",
    ) -> dict[str, Any]:
        graph = ExecutionGraphModel.from_dag_json(execution_graph)
        snapshot = self._runner.debugger.inspect_node(graph, node_id, phase=phase)
        if snapshot is None:
            raise KeyError(f"Node not found: {node_id}")
        return {"node_id": node_id, "phase": phase, "snapshot": snapshot}

    @staticmethod
    def rollback_state(state_snapshot: dict, version_id: str) -> dict[str, Any]:
        state = AgentState.from_api_snapshot(state_snapshot)
        restored = GraphRuntimeRunner.rollback_state(state, version_id)
        return {
            "version_id": restored.state_version_id,
            "branch_id": restored.branch_id,
            "state_snapshot": restored.api_snapshot(),
        }

    @staticmethod
    def fork_state(
        state_snapshot: dict,
        *,
        from_version_id: str | None,
        branch_name: str | None,
    ) -> dict[str, Any]:
        state = AgentState.from_api_snapshot(state_snapshot)
        _, branch_id = GraphRuntimeRunner.fork_branch(
            state,
            from_version_id=from_version_id,
            branch_name=branch_name,
        )
        return {
            "branch_id": branch_id,
            "state_version_id": state.state_version_id,
            "state_snapshot": state.api_snapshot(),
        }

    @staticmethod
    def diff_state(state_snapshot: dict, version_a: str, version_b: str) -> dict[str, Any]:
        state = AgentState.from_api_snapshot(state_snapshot)
        diff = GraphRuntimeRunner.diff_versions(state, version_a, version_b)
        return {"version_a": version_a, "version_b": version_b, "diff": diff}

    async def replay_branch(
        self,
        *,
        state_snapshot: dict,
        from_version_id: str,
        query: str,
        session_id: str,
        branch_name: str | None,
    ) -> GraphExecuteResponse:
        return await self._runner.replay_from_branch(
            state_snapshot,
            from_version_id=from_version_id,
            query=query,
            session_id=session_id,
            branch_name=branch_name,
            policy=ExecutionPolicy(capture_state_snapshots=True),
        )
