"""Replay and compare persisted graph executions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from graph.runtime.agent_state import AgentState
from graph.runtime.execution_policy import ExecutionPolicy
from persistence.stores import (
    ExecutionStore,
    NodeStore,
    SessionStore,
    StateStore,
    ToolStore,
)

if TYPE_CHECKING:
    from graph.runtime.runner import GraphRuntimeRunner


class ExecutionReplayService:
    """Load, replay, compare, and restore persisted executions."""

    def __init__(
        self,
        *,
        execution_store: ExecutionStore,
        node_store: NodeStore,
        tool_store: ToolStore,
        state_store: StateStore,
        session_store: SessionStore,
        runner: GraphRuntimeRunner | None = None,
    ) -> None:
        self._execution_store = execution_store
        self._node_store = node_store
        self._tool_store = tool_store
        self._state_store = state_store
        self._session_store = session_store
        self._runner = runner

    def bind_runner(self, runner: GraphRuntimeRunner) -> None:
        self._runner = runner

    async def get_execution(self, execution_id: str) -> dict[str, Any] | None:
        execution = await self._execution_store.get(execution_id)
        if execution is None:
            return None

        nodes = await self._node_store.list_by_execution(execution_id)
        tools = await self._tool_store.list_by_execution(execution_id)
        versions = await self._state_store.list_by_execution(execution_id)

        return {
            "execution": execution.model_dump(mode="json"),
            "nodes": [n.model_dump(mode="json") for n in nodes],
            "tool_calls": [t.model_dump(mode="json") for t in tools],
            "state_versions": [v.model_dump(mode="json") for v in versions],
        }

    async def replay_execution(
        self,
        execution_id: str,
        *,
        node_id: str | None = None,
        compare_with: str | None = None,
    ) -> dict[str, Any]:
        execution = await self._execution_store.get(execution_id)
        if execution is None:
            raise KeyError(f"Execution not found: {execution_id}")

        nodes = await self._node_store.list_by_execution(execution_id)

        if compare_with:
            comparison = await self.compare_executions(execution_id, compare_with)
            return {"comparison": comparison}

        if node_id:
            return self._replay_single_node(execution, nodes, node_id)

        steps = self._steps_from_nodes(nodes)
        final_state = self._apply_snapshots(nodes)
        final_result_match = (
            final_state is not None
            and final_state.final_result == execution.final_result
        )
        hash_consistent = all(
            step["output_state_hash"] == nodes[index].output_state_hash
            for index, step in enumerate(steps)
        )
        all_replayed = all(step["replayed"] for step in steps)

        return {
            "execution_id": execution_id,
            "mode": "full",
            "steps": steps,
            "original_node_count": len(nodes),
            "replayed_node_count": len(steps),
            "consistent": (
                len(steps) == len(nodes)
                and hash_consistent
                and all_replayed
                and final_result_match
            ),
            "hash_consistent": hash_consistent,
            "all_replayed": all_replayed,
            "final_result_match": final_result_match,
            "replayed_final_result": final_state.final_result if final_state else None,
        }

    async def compare_executions(
        self,
        execution_id_a: str,
        execution_id_b: str,
    ) -> dict[str, Any]:
        detail_a = await self.get_execution(execution_id_a)
        detail_b = await self.get_execution(execution_id_b)
        if detail_a is None or detail_b is None:
            missing = execution_id_a if detail_a is None else execution_id_b
            raise KeyError(f"Execution not found: {missing}")

        nodes_a = detail_a["nodes"]
        nodes_b = detail_b["nodes"]
        node_diffs: list[dict[str, Any]] = []

        max_len = max(len(nodes_a), len(nodes_b))
        for index in range(max_len):
            left = nodes_a[index] if index < len(nodes_a) else None
            right = nodes_b[index] if index < len(nodes_b) else None
            if left is None or right is None:
                node_diffs.append({"index": index, "left": left, "right": right, "match": False})
                continue
            match = (
                left["node_id"] == right["node_id"]
                and left.get("output_state_hash") == right.get("output_state_hash")
            )
            node_diffs.append(
                {
                    "index": index,
                    "node_id": left["node_id"],
                    "match": match,
                    "left_output_hash": left.get("output_state_hash"),
                    "right_output_hash": right.get("output_state_hash"),
                },
            )

        exec_a = detail_a["execution"]
        exec_b = detail_b["execution"]
        return {
            "execution_a": execution_id_a,
            "execution_b": execution_id_b,
            "final_result_match": exec_a.get("final_result") == exec_b.get("final_result"),
            "status_match": exec_a.get("status") == exec_b.get("status"),
            "node_count_a": len(nodes_a),
            "node_count_b": len(nodes_b),
            "node_count_match": len(nodes_a) == len(nodes_b),
            "tool_call_count_a": len(detail_a["tool_calls"]),
            "tool_call_count_b": len(detail_b["tool_calls"]),
            "node_diffs": node_diffs,
            "all_nodes_match": all(d.get("match") for d in node_diffs if "match" in d),
        }

    async def restore_session(
        self,
        session_id: str,
        *,
        query: str | None = None,
    ) -> dict[str, Any]:
        if self._runner is None:
            raise RuntimeError("Graph runner not bound for session restore")

        session = await self._session_store.get(session_id)
        if session is None or not session.last_state_snapshot:
            raise KeyError(f"No restorable session: {session_id}")

        restored_state = AgentState.from_api_snapshot(session.last_state_snapshot)
        run_query = query or restored_state.query
        if not run_query:
            raise ValueError("Query required to continue execution")

        if query:
            restored_state.query = query
            restored_state.append_message("user", query)

        policy = ExecutionPolicy(capture_state_snapshots=True)
        response = await self._runner.invoke(
            run_query,
            session_id=session_id,
            policy=policy,
            initial_state=restored_state,
        )
        return {
            "session_id": session_id,
            "restored_from_execution_id": session.last_execution_id,
            "result": response.model_dump(),
        }

    @staticmethod
    def _steps_from_nodes(nodes: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "node_id": node.node_id,
                "sequence": node.sequence,
                "input_state_hash": node.input_state_hash,
                "output_state_hash": node.output_state_hash,
                "replayed": node.output_state is not None,
            }
            for node in nodes
        ]

    @staticmethod
    def _apply_snapshots(nodes: list[Any]) -> AgentState | None:
        state: AgentState | None = None
        for node in nodes:
            if node.output_state is None:
                continue
            if state is None and node.input_state:
                state = AgentState.from_api_snapshot(node.input_state)
            if state is None:
                state = AgentState.from_api_snapshot(node.output_state)
            else:
                state = state.apply_snapshot(node.output_state)
        return state

    def _replay_single_node(
        self,
        execution: Any,
        nodes: list[Any],
        node_id: str,
    ) -> dict[str, Any]:
        target = next((n for n in nodes if n.node_id == node_id), None)
        if target is None:
            raise KeyError(f"Node not found in replay: {node_id}")

        prefix = [n for n in nodes if n.sequence < target.sequence]
        state = self._apply_snapshots(prefix)
        if state is None and target.input_state:
            state = AgentState.from_api_snapshot(target.input_state)

        replayed_state = (
            state.apply_snapshot(target.output_state)
            if state is not None and target.output_state
            else state
        )

        return {
            "execution_id": execution.execution_id,
            "mode": "single_node",
            "node_id": target.node_id,
            "sequence": target.sequence,
            "input_state_hash": target.input_state_hash,
            "output_state_hash": target.output_state_hash,
            "input_state": target.input_state,
            "output_state": target.output_state,
            "replayed": target.output_state is not None,
            "replayed_final_result": replayed_state.final_result if replayed_state else None,
        }

    @staticmethod
    def _initial_state_for_replay(execution: Any, nodes: list[Any]) -> AgentState | None:
        if not nodes or not nodes[0].input_state:
            return None
        state = AgentState.from_api_snapshot(nodes[0].input_state)
        state.session_id = execution.session_id
        state.query = execution.query
        return state
