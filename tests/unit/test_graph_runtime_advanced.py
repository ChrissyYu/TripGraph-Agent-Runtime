"""Unit tests for parallel execution, state versioning, and hierarchical graphs."""

from __future__ import annotations

import asyncio

import pytest

from graph.runtime.agent_state import AgentState
from graph.runtime.compiler.plan_compiler import PlanGraphCompiler
from graph.runtime.core.edge import EdgeKind
from graph.runtime.core.graph import END, Graph
from graph.runtime.execution_policy import ExecutionPolicy
from graph.runtime.hierarchical import AgentNode, StateMapper, SubgraphNode
from graph.runtime.runner import GraphRuntimeRunner
from graph.runtime.state_merge import MergeStrategy, StateMergeConflictError, merge_states
from graph.runtime.state_versioning import StateVersionManager
from schemas.plan import Plan, PlanStep
from tests.integration.test_graph_execute import USER_QUERY, graph_runner  # noqa: F401


@pytest.mark.asyncio
async def test_parallel_fanout_gather_and_join() -> None:
    order: list[str] = []

    def make_node(name: str):
        async def _run(state: AgentState) -> AgentState:
            await asyncio.sleep(0.01)
            order.append(name)
            state.observations[name] = True
            return state

        return _run

    graph = Graph(graph_id="parallel_test", entry="start", max_iterations=20)
    graph.add_node("start", make_node("start"))
    graph.add_node("branch_a", make_node("branch_a"))
    graph.add_node("branch_b", make_node("branch_b"))
    graph.add_node("after_join", make_node("after_join"))
    graph.add_parallel_fanout("start", ["branch_a", "branch_b"], join_node="join")
    graph.add_join_node("join", wait_for=["branch_a", "branch_b"], next_node="after_join")
    graph.add_edge("after_join", END)

    state = AgentState(session_id="p1", query="parallel")
    final = await graph.invoke(state, policy=ExecutionPolicy())

    assert final.observations.get("branch_a") is True
    assert final.observations.get("branch_b") is True
    assert final.observations.get("after_join") is True
    assert "branch_a" in order and "branch_b" in order
    assert final.version_store is not None
    assert len(final.version_store.versions) >= 4
    assert final.execution_graph is not None
    parallel_edges = [e for e in final.execution_graph.edge_records if e.kind == EdgeKind.PARALLEL.value]
    assert len(parallel_edges) >= 2


def test_state_merge_deep_merge() -> None:
    left = AgentState(session_id="s", query="q")
    left.observations["a"] = 1
    right = AgentState(session_id="s", query="q")
    right.observations["b"] = 2

    merged = merge_states(left, [right], strategy=MergeStrategy.DEEP_MERGE)
    assert merged.observations["a"] == 1
    assert merged.observations["b"] == 2


def test_state_merge_last_wins() -> None:
    left = AgentState(session_id="s", query="q", final_result="left")
    right = AgentState(session_id="s", query="q", final_result="right")
    merged = merge_states(left, [right], strategy=MergeStrategy.LAST_WINS)
    assert merged.final_result == "right"


def test_state_merge_fail_on_conflict() -> None:
    left = AgentState(session_id="s", query="q", final_result="A")
    right = AgentState(session_id="s", query="q", final_result="B")

    with pytest.raises(StateMergeConflictError):
        merge_states(left, [right], strategy=MergeStrategy.FAIL_ON_CONFLICT)


@pytest.mark.asyncio
async def test_state_versioning_commit_rollback_diff_fork() -> None:
    state = AgentState(session_id="v1", query="version test")
    v1 = StateVersionManager.commit(state, node_id="n1")
    state.observations["step"] = 1
    v2 = StateVersionManager.commit(state, node_id="n2")

    assert state.version_store is not None
    assert len(state.version_store.versions) == 2
    assert v2.parent_version_id == v1.version_id

    diff = StateVersionManager.diff(state, v1.version_id, v2.version_id)
    assert "observations" in diff

    restored = StateVersionManager.rollback(state, v1.version_id)
    assert restored.observations.get("step") is None

    branch_id = StateVersionManager.fork_branch(restored, from_version_id=v1.version_id, branch_name="exp")
    assert branch_id == "exp"
    assert restored.observations.get("step") is None
    assert restored.version_store.branch_id == "exp"


@pytest.mark.asyncio
async def test_subgraph_node_state_mapping() -> None:
    async def child_planner(state: AgentState) -> AgentState:
        state.final_result = f"child:{state.query}"
        state.observations["child_done"] = True
        return state

    child = Graph(graph_id="child_graph", entry="child_planner", max_iterations=5)
    child.add_node("child_planner", child_planner)
    child.add_edge("child_planner", END)

    mapper = StateMapper.scoped(prefix="research")
    agent = AgentNode("research_agent", child, mapper=mapper, description="Research sub-agent")

    parent = AgentState(session_id="h1", query="tokyo trip")
    parent.memory["topic"] = "travel"

    result = await agent(parent)
    assert result.memory.get("research_result") == "child:tokyo trip"
    assert "research" in result.observations
    assert result.memory.get("agent_calls")


def test_plan_compiler_parallel_levels() -> None:
    from unittest.mock import MagicMock

    deps = MagicMock()
    plan = Plan(
        goal="parallel plan",
        steps=[
            PlanStep(id=1, task="task A", tool_hint="search"),
            PlanStep(id=2, task="task B", tool_hint="search"),
            PlanStep(id=3, task="task C", tool_hint="search", dependency=[1, 2]),
        ],
    )
    graph = PlanGraphCompiler(deps, merge_strategy=MergeStrategy.DEEP_MERGE).compile(plan)
    assert graph.metadata["parallel_levels"] == [[1, 2], [3]]
    fan = graph.fan_out_for("plan_entry")
    assert fan is not None
    assert set(fan.branches) == {"step_1", "step_2"}


@pytest.mark.asyncio
async def test_workflow_execution_uses_agent_node(graph_runner) -> None:
    result = await graph_runner.invoke(USER_QUERY, session_id="agent-node-test")
    assert result.version_summary is not None
    assert result.version_summary["version_count"] >= 5
    agent_events = [
        e for e in result.graph_trace if e.node_id == "plan_executor" and e.event == "agent_invoke"
    ]
    assert agent_events


@pytest.mark.asyncio
async def test_api_state_rollback_fork_diff(graph_runner, async_client) -> None:
    runner_state = graph_runner._initial_state(USER_QUERY, session_id="state-api-inner")
    final = await graph_runner.workflow.invoke(runner_state)
    snap = final.api_snapshot()
    assert snap.get("version_store")
    assert len(snap["version_store"]["versions"]) >= 2

    v1 = snap["version_store"]["versions"][0]["version_id"]
    v2 = snap["version_store"]["versions"][1]["version_id"]

    diff_resp = await async_client.post(
        "/api/v1/graph_state/diff",
        json={"version_a": v1, "version_b": v2, "state_snapshot": snap},
    )
    assert diff_resp.status_code == 200

    fork_resp = await async_client.post(
        "/api/v1/graph_state/fork",
        json={
            "session_id": "state-api",
            "from_version_id": v1,
            "branch_name": "experiment",
            "state_snapshot": snap,
        },
    )
    assert fork_resp.status_code == 200
    assert fork_resp.json()["branch_id"] == "experiment"

    rollback_resp = await async_client.post(
        "/api/v1/graph_state/rollback",
        json={"session_id": "state-api", "version_id": v1, "state_snapshot": snap},
    )
    assert rollback_resp.status_code == 200
    assert rollback_resp.json()["version_id"] == v1


@pytest.mark.asyncio
async def test_replay_from_branch(graph_runner) -> None:
    runner_state = graph_runner._initial_state(USER_QUERY, session_id="branch-replay")
    final = await graph_runner.workflow.invoke(runner_state)
    snap = final.api_snapshot()
    first_version = snap["version_store"]["versions"][0]["version_id"]

    forked = await graph_runner.replay_from_branch(
        snap,
        from_version_id=first_version,
        query=USER_QUERY,
        session_id="branch-replay-2",
        branch_name="replay_branch",
    )
    assert forked.session_id == "branch-replay-2"
    assert forked.version_summary["branch_id"] == "replay_branch"
