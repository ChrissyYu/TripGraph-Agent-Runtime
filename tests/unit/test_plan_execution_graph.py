"""Unit tests for PlanExecutionGraph DAG view."""

from __future__ import annotations

import json

import pytest

from plan.executor import PlanExecutor
from plan.graph import PlanExecutionGraph
from plan.state import PlanState
from schemas.plan import Plan, PlanStep, StepResult, StepStatus
from schemas.plan_graph import GraphNodeStatus
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from tools.reliability import ToolReliabilityPolicy


def _plan() -> Plan:
    return Plan(
        goal="上海3日游",
        steps=[
            PlanStep(id=1, task="查天气", tool_hint="weather"),
            PlanStep(id=2, task="规划路线", tool_hint="map", dependency=[1]),
            PlanStep(id=3, task="算预算", tool_hint="budget", dependency=[1, 2]),
        ],
    )


def test_graph_builds_nodes_and_edges() -> None:
    graph = PlanExecutionGraph.from_plan(_plan(), session_id="dag-1")
    snapshot = graph.get_graph_snapshot()

    assert snapshot.goal == "上海3日游"
    assert len(snapshot.nodes) == 3
    assert len(snapshot.edges) == 3
    assert all(n.status == GraphNodeStatus.PENDING for n in snapshot.nodes)
    assert {e.source for e in snapshot.edges} <= {1, 2}
    assert {e.target for e in snapshot.edges} == {2, 3}


def test_graph_sync_from_state_reflects_progress() -> None:
    graph = PlanExecutionGraph.from_plan(_plan())
    state = PlanState.from_plan(_plan())

    state.set_step_status(1, StepStatus.RUNNING)
    state.current_step = 1
    graph.sync_from_state(state)

    snap = graph.get_graph_snapshot()
    node1 = snap.node_map()[1]
    assert node1.status == GraphNodeStatus.RUNNING
    assert snap.current_step == 1

    state.record_step_result(
        StepResult(step_id=1, task="查天气", status=StepStatus.COMPLETED, tool_name="weather"),
    )
    state.current_step = None
    graph.sync_from_state(state)

    snap = graph.get_graph_snapshot()
    assert snap.node_map()[1].status == GraphNodeStatus.SUCCESS
    assert snap.node_map()[2].status == GraphNodeStatus.PENDING


def test_export_graph_json_structure() -> None:
    graph = PlanExecutionGraph.from_plan(_plan(), session_id="export-test")
    payload = json.loads(graph.export_graph_json())

    assert payload["session_id"] == "export-test"
    assert "nodes" in payload
    assert "edges" in payload
    assert payload["nodes"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_plan_executor_exposes_graph_snapshot() -> None:
    registry = ToolRegistry.default()
    tool_executor = ToolExecutor(registry, reliability=ToolReliabilityPolicy(max_retries=0))
    plan_executor = PlanExecutor(tool_executor)

    state = PlanState.from_plan(_plan())
    state.global_context.update({"city": "上海", "days": 3, "origin": "A", "destination": "B"})

    await plan_executor.execute(state.plan, state)

    snapshot = plan_executor.get_graph_snapshot()
    assert len(snapshot.nodes) == 3
    assert all(n.status == GraphNodeStatus.SUCCESS for n in snapshot.nodes)

    exported = json.loads(plan_executor.export_graph_json())
    assert exported["goal"] == "上海3日游"
    assert len(exported["edges"]) == 3
