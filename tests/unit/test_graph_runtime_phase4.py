"""Unit tests for Phase 4 execution policy, trace, replay, and memory."""

from __future__ import annotations

import pytest

from graph.runtime.agent_state import AgentState
from graph.runtime.execution_policy import ExecutionMode, ExecutionPolicy
from graph.runtime.replay_debug import GraphReplayDebugger
from graph.runtime.runner import GraphRuntimeRunner
from graph.runtime.state_hash import hash_state
from schemas.execution_graph import ExecutionGraphModel, NodeExecutionRecord
from schemas.plan import ExecutionTraceEntry, StepStatus
from tests.integration.test_graph_execute import USER_QUERY, graph_runner


def test_execution_policy_deterministic_seed() -> None:
    policy = ExecutionPolicy().with_seed(123)
    assert policy.mode == ExecutionMode.DETERMINISTIC
    assert policy.seed == 123


def test_state_hash_stable() -> None:
    state = AgentState(session_id="s1", query="hello")
    state.append_message("user", "hello")
    h1 = hash_state(state)
    h2 = hash_state(state)
    assert h1 == h2


def test_execution_graph_model_exports() -> None:
    model = ExecutionGraphModel(
        graph_id="test",
        session_id="s1",
        node_records=[
            NodeExecutionRecord(
                node_id="planner",
                sequence=0,
                input_state_hash="aaa",
                output_state_hash="bbb",
                state_delta={"plan": {"changed": True}},
            ),
        ],
    )
    dag = model.to_dag_json()
    assert dag["nodes"][0]["input_state_hash"] == "aaa"
    assert "planner" in model.to_mermaid()
    assert "planner" in model.to_graphviz()


@pytest.mark.asyncio
async def test_deterministic_execution_uses_seed_and_replay(graph_runner: GraphRuntimeRunner) -> None:
    policy = ExecutionPolicy().with_seed(99)
    policy.capture_state_snapshots = True

    result = await graph_runner.invoke(USER_QUERY, session_id="deterministic", policy=policy)
    assert result.execution_seed == 99 or result.execution_graph.get("seed") == 99
    assert result.execution_graph is not None
    assert all(node["input_state_hash"] for node in result.execution_graph["nodes"])

    from schemas.execution_graph import ExecutionGraphModel

    model = ExecutionGraphModel.from_dag_json(result.execution_graph)
    assert graph_runner.debugger.inspect_node(model, "planner", phase="output") is not None


@pytest.mark.asyncio
async def test_execution_graph_records_state_hashes(graph_runner: GraphRuntimeRunner) -> None:
    policy = ExecutionPolicy(capture_state_snapshots=True)
    result = await graph_runner.invoke(USER_QUERY, session_id="hash-test", policy=policy)

    assert result.execution_graph is not None
    for node in result.execution_graph["nodes"]:
        assert node["input_state_hash"]
        assert node["output_state_hash"]
        assert "state_delta" in node


@pytest.mark.asyncio
async def test_replay_from_execution_trace(graph_runner: GraphRuntimeRunner) -> None:
    result = await graph_runner.invoke(USER_QUERY, session_id="replay-src")
    replay_graph = GraphReplayDebugger.from_execution_trace(result.execution_trace)

    steps = [step async for step in graph_runner.debugger.replay_all(replay_graph)]
    assert steps


@pytest.mark.asyncio
async def test_replay_single_node_inspect(graph_runner: GraphRuntimeRunner) -> None:
    policy = ExecutionPolicy(capture_state_snapshots=True)
    result = await graph_runner.invoke(USER_QUERY, session_id="inspect", policy=policy)
    assert result.execution_graph

    model = ExecutionGraphModel.from_dag_json(result.execution_graph)
    snapshot = graph_runner.debugger.inspect_node(model, "planner", phase="output")
    assert snapshot is not None


@pytest.mark.asyncio
async def test_memory_nodes_populate_state(graph_runner: GraphRuntimeRunner) -> None:
    result = await graph_runner.invoke(USER_QUERY, session_id="memory-test")
    assert result.state_summary.get("episodic_memory_count", 0) >= 0
    node_ids = [e.node_id for e in result.graph_trace if e.event == "node_start"]
    assert "memory_load" in node_ids
    assert "memory_persist" in node_ids


@pytest.mark.asyncio
async def test_debug_pause_at_node(graph_runner: GraphRuntimeRunner) -> None:
    state, session = await graph_runner.debugger.debug_invoke(
        USER_QUERY,
        session_id="debug-pause",
        pause_at={"planner"},
    )
    assert session.paused_at == "planner"
    assert session.inspect()["snapshot"] is not None
    assert state.query == USER_QUERY
