"""System-level tests for GraphRuntime: parallel, versioning, determinism."""

from __future__ import annotations

import asyncio
import copy
import time
from typing import Any

import pytest

from graph.runtime.agent_state import AgentState
from graph.runtime.core.graph import END, Graph
from graph.runtime.execution_policy import ExecutionPolicy
from graph.runtime.runner import GraphRuntimeRunner
from graph.runtime.state_merge import MergeStrategy
from graph.runtime.state_versioning import StateVersionManager
from schemas.graph_runtime import GraphTraceEntry
from tests.integration.test_graph_execute import USER_QUERY, graph_runner  # noqa: F401

# User-facing aliases mapped to runtime merge strategies
MERGE_LAST_WRITE = MergeStrategy.LAST_WINS
MERGE_CONCAT = MergeStrategy.MERGE_LISTS
MERGE_CUSTOM = MergeStrategy.DEEP_MERGE

_VOLATILE_TRACE_DATA_KEYS = frozenset(
    {"state_version_id", "input_state_hash", "output_state_hash", "state_delta_keys"},
)


def _normalize_graph_trace(trace: list[GraphTraceEntry]) -> list[tuple[str, str, dict[str, Any]]]:
    """Strip non-deterministic fields while preserving execution structure."""
    normalized: list[tuple[str, str, dict[str, Any]]] = []
    for entry in trace:
        data = {
            key: value
            for key, value in entry.data.items()
            if key not in _VOLATILE_TRACE_DATA_KEYS
        }
        normalized.append((entry.node_id, entry.event, data))
    return normalized


def _graph_trace_skeleton(trace: list[GraphTraceEntry]) -> list[tuple[str, str]]:
    return [(entry.node_id, entry.event) for entry in trace]


def _build_parallel_merge_graph(*, merge_strategy: MergeStrategy) -> Graph:
    """Fan-out graph where branches write overlapping and distinct fields."""

    async def _mark_started(state: AgentState) -> AgentState:
        state.observations["started"] = True
        return state

    def branch_node(name: str, marker: str):
        async def _run(state: AgentState) -> AgentState:
            state.observations["winner"] = marker
            state.observations[f"seen_{name}"] = True
            state.messages.append({"role": "system", "content": f"branch:{name}"})
            state.final_result = marker
            return state

        return _run

    graph = Graph(
        graph_id="merge_strategy_system_test",
        entry="start",
        max_iterations=10,
        merge_strategy=merge_strategy,
    )
    graph.add_node("start", _mark_started)
    graph.add_node("branch_a", branch_node("a", "A"))
    graph.add_node("branch_b", branch_node("b", "B"))
    graph.add_parallel_fanout("start", ["branch_a", "branch_b"], join_node="join")
    graph.add_join_node("join", wait_for=["branch_a", "branch_b"], next_node=END)
    return graph


@pytest.mark.asyncio
async def test_fan_out_nodes_execute_in_parallel() -> None:
    """Branches under a fan-out must overlap in wall-clock time."""
    lock = asyncio.Lock()
    stats = {"active": 0, "max_concurrent": 0}
    branch_delay = 0.08

    def slow_branch(name: str):
        async def _run(state: AgentState) -> AgentState:
            async with lock:
                stats["active"] += 1
                stats["max_concurrent"] = max(stats["max_concurrent"], stats["active"])
            await asyncio.sleep(branch_delay)
            async with lock:
                stats["active"] -= 1
            state.observations[name] = True
            return state

        return _run

    graph = Graph(graph_id="parallel_timing", entry="start", max_iterations=10)

    async def _noop(state: AgentState) -> AgentState:
        return state

    graph.add_node("start", _noop)
    graph.add_node("branch_x", slow_branch("branch_x"))
    graph.add_node("branch_y", slow_branch("branch_y"))
    graph.add_parallel_fanout("start", ["branch_x", "branch_y"], join_node="join")
    graph.add_join_node("join", wait_for=["branch_x", "branch_y"], next_node=END)

    state = AgentState(session_id="parallel-sys", query="parallel timing")
    started = time.monotonic()
    final = await graph.invoke(state, policy=ExecutionPolicy())
    elapsed = time.monotonic() - started

    assert final.observations.get("branch_x") is True
    assert final.observations.get("branch_y") is True
    assert stats["max_concurrent"] >= 2, "fan-out branches did not overlap"
    assert elapsed < branch_delay * 1.75, (
        f"expected parallel elapsed ~{branch_delay}s, got {elapsed:.3f}s"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("strategy", "alias"),
    [
        (MERGE_LAST_WRITE, "last_write"),
        (MERGE_CONCAT, "concat"),
        (MERGE_CUSTOM, "custom"),
    ],
)
async def test_parallel_merge_strategy_correctness(strategy: MergeStrategy, alias: str) -> None:
    graph = _build_parallel_merge_graph(merge_strategy=strategy)
    state = AgentState(session_id=f"merge-{alias}", query="merge test")
    final = await graph.invoke(state, policy=ExecutionPolicy())

    if strategy is MERGE_LAST_WRITE:
        assert final.observations.get("winner") == "B"
        assert final.final_result == "B"
        assert "seen_a" not in final.observations
    elif strategy is MERGE_CONCAT:
        assert final.observations.get("winner") == "B"
        contents = [msg["content"] for msg in final.messages if msg.get("role") == "system"]
        assert "branch:a" in contents
        assert "branch:b" in contents
    else:  # DEEP_MERGE / custom
        assert final.observations.get("winner") == "B"
        assert final.observations.get("seen_a") is True
        assert final.observations.get("seen_b") is True
        assert final.observations.get("started") is True


@pytest.mark.asyncio
async def test_graph_runner_passes_merge_strategy_to_plan_subgraph(
    graph_runner: GraphRuntimeRunner,
) -> None:
    """GraphRuntimeRunner wires merge_strategy into compiled plan execution."""
    policy = ExecutionPolicy(capture_state_snapshots=True)
    result = await graph_runner.invoke(
        USER_QUERY,
        session_id="runner-merge-strategy",
        policy=policy,
        merge_strategy=MergeStrategy.DEEP_MERGE.value,
    )
    assert result.runtime == "graph"
    assert result.version_summary is not None
    assert result.version_summary["version_count"] >= 1
    assert result.final_result


@pytest.mark.asyncio
async def test_state_version_fork_rollback_replay_consistency(
    graph_runner: GraphRuntimeRunner,
) -> None:
    """fork → rollback → replay_from_branch yields consistent versioned state."""
    policy = ExecutionPolicy(capture_state_snapshots=True)
    runner_state = graph_runner._initial_state(USER_QUERY, session_id="version-consistency")
    baseline = await graph_runner.workflow.invoke(copy.deepcopy(runner_state), policy=policy)
    baseline_snap = baseline.api_snapshot()
    store = baseline.version_store
    assert store is not None
    assert len(store.versions) >= 3

    anchor = store.versions[1]
    latest = store.versions[-1]

    working = AgentState.from_api_snapshot(baseline_snap)
    branch_id = StateVersionManager.fork_branch(
        working,
        from_version_id=anchor.version_id,
        branch_name="consistency_branch",
    )
    assert branch_id == "consistency_branch"
    assert working.branch_id == "consistency_branch"
    assert working.state_version_id == anchor.version_id
    _assert_snapshot_fields_match(working.snapshot(), anchor.snapshot)

    rolled = StateVersionManager.rollback(working, anchor.version_id)
    _copy_agent_state(working, rolled)
    _assert_snapshot_fields_match(working.snapshot(), anchor.snapshot)

    fork_snap = working.api_snapshot()
    replayed = await graph_runner.replay_from_branch(
        fork_snap,
        from_version_id=anchor.version_id,
        query=USER_QUERY,
        session_id="version-consistency-replay",
        branch_name="consistency_replay",
        policy=policy,
    )

    assert replayed.version_summary is not None
    assert replayed.version_summary["branch_id"] == "consistency_replay"
    assert replayed.final_result
    assert "上海" in replayed.final_result

    replay_diff = StateVersionManager.diff(
        working,
        anchor.version_id,
        latest.version_id,
    )
    assert replay_diff, "anchor and latest versions should differ after full run"

    rolled_again = StateVersionManager.rollback(working, anchor.version_id)
    _assert_snapshot_fields_match(rolled_again.snapshot(), anchor.snapshot)


@pytest.mark.asyncio
async def test_deterministic_execution_identical_graph_trace(
    graph_runner: GraphRuntimeRunner,
) -> None:
    """Same query + seed produces identical graph_trace structure."""
    policy = ExecutionPolicy().with_seed(42)
    policy.capture_state_snapshots = True

    result_a = await graph_runner.invoke(
        USER_QUERY,
        session_id="deterministic-a",
        policy=policy,
    )
    result_b = await graph_runner.invoke(
        USER_QUERY,
        session_id="deterministic-b",
        policy=policy,
    )

    skeleton_a = _graph_trace_skeleton(result_a.graph_trace)
    skeleton_b = _graph_trace_skeleton(result_b.graph_trace)
    assert skeleton_a == skeleton_b
    assert len(skeleton_a) > 0

    normalized_a = _normalize_graph_trace(result_a.graph_trace)
    normalized_b = _normalize_graph_trace(result_b.graph_trace)
    assert normalized_a == normalized_b

    assert result_a.execution_seed == 42 or result_a.execution_graph.get("seed") == 42
    assert result_b.execution_seed == 42 or result_b.execution_graph.get("seed") == 42


@pytest.mark.asyncio
async def test_state_version_manager_lineage_after_runner_invoke(
    graph_runner: GraphRuntimeRunner,
) -> None:
    """StateVersionManager lineage is coherent after a full GraphRuntimeRunner run."""
    runner_state = graph_runner._initial_state(USER_QUERY, session_id="lineage-test")
    final = await graph_runner.workflow.invoke(
        runner_state,
        policy=ExecutionPolicy(capture_state_snapshots=True),
    )
    store = final.version_store
    assert store is not None
    assert store.current_version_id

    lineage = store.lineage()
    assert len(lineage) == len(store.versions)
    assert lineage[-1].version_id == store.current_version_id

    for index, version in enumerate(lineage):
        if index == 0:
            assert version.parent_version_id is None
        else:
            assert version.parent_version_id == lineage[index - 1].version_id


def _copy_agent_state(target: AgentState, source: AgentState) -> None:
    for key in AgentState.model_fields:
        object.__setattr__(target, key, getattr(source, key))


def _assert_snapshot_fields_match(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    for key in ("query", "observations", "messages", "current_step", "final_result"):
        assert actual.get(key) == expected.get(key)
