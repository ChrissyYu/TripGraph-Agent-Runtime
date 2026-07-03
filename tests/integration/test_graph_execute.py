"""Integration tests for Phase 4 graph-native runtime."""

from __future__ import annotations

import json

import pytest

from agents.planner import PlannerAgent
from core.llm.rule_based import RuleBasedLLMClient
from memory.composite import CompositeMemory
from graph.runtime.deps import RuntimeDependencies
from graph.runtime.runner import GraphRuntimeRunner
from plan.execution_critic import ExecutionCritic
from plan.executor import PlanExecutor
from plan.replanning_controller import ReplanningController
from plan.resolver import StepToolResolver
from plan.state import PlanState
from plan.validator import PlanValidator
from schemas.execution_critic import ExecutionCritique
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from tools.reliability import ToolReliabilityPolicy
from tools.router import ToolSelectionRouter

USER_QUERY = "规划上海3日游并计算预算"


@pytest.fixture
def graph_runner() -> GraphRuntimeRunner:
    registry = ToolRegistry.default()
    tool_executor = ToolExecutor(registry, reliability=ToolReliabilityPolicy(max_retries=0))
    planner = PlannerAgent(RuleBasedLLMClient(), tool_registry=registry)
    validator = PlanValidator(registry)
    resolver = StepToolResolver()
    plan_executor = PlanExecutor(
        tool_executor,
        planner=planner,
        validator=validator,
        resolver=resolver,
        summarizer=planner.llm,
    )
    deps = RuntimeDependencies(
        planner=planner,
        tool_router=ToolSelectionRouter(registry),
        plan_executor=plan_executor,
        critic=ExecutionCritic(planner.llm),
        replanner=ReplanningController(planner, validator),
        resolver=resolver,
        validator=validator,
        memory_store=CompositeMemory(),
    )
    return GraphRuntimeRunner(deps)


def _critique(*, need_replan: bool) -> ExecutionCritique:
    return ExecutionCritique(
        score=0.4 if need_replan else 0.95,
        critique="needs budget" if need_replan else "ok",
        need_replan=need_replan,
        goal_completed=not need_replan,
        missing_info=["trip budget"] if need_replan else [],
    )


@pytest.mark.asyncio
async def test_graph_execute_full_flow(graph_runner: GraphRuntimeRunner) -> None:
    result = await graph_runner.invoke(USER_QUERY, session_id="graph-shanghai")

    assert result.runtime == "graph"
    assert result.plan is not None
    assert len(result.plan.steps) >= 3
    assert result.final_result
    assert "上海" in result.final_result
    assert "预算" in result.final_result

    # graph node order
    node_ids = [entry.node_id for entry in result.graph_trace if entry.event == "node_start"]
    assert node_ids.index("memory_load") < node_ids.index("planner")
    assert node_ids.index("planner") < node_ids.index("execution")
    assert node_ids.index("execution") < node_ids.index("critic")
    assert "compile_plan" in node_ids
    assert "router" in node_ids
    assert result.execution_graph is not None
    assert result.execution_graph_mermaid
    assert result.execution_graph_dot

    assert len(result.execution_trace) >= 3
    assert all(entry.success is True for entry in result.execution_trace)
    assert result.execution_critique is not None
    assert result.execution_critique.goal_completed is True

    tool_hints = [s.tool_hint for s in result.plan.steps if s.tool_hint]
    assert "weather" in tool_hints
    assert "budget" in tool_hints


@pytest.mark.asyncio
async def test_graph_critic_replan_loop() -> None:
    registry = ToolRegistry.default()
    tool_executor = ToolExecutor(registry, reliability=ToolReliabilityPolicy(max_retries=0))
    planner = PlannerAgent(RuleBasedLLMClient(), tool_registry=registry)
    validator = PlanValidator(registry)
    resolver = StepToolResolver()
    plan_executor = PlanExecutor(
        tool_executor,
        planner=planner,
        validator=validator,
        resolver=resolver,
        summarizer=planner.llm,
    )

    class FirstPassCritic(ExecutionCritic):
        def __init__(self) -> None:
            super().__init__(llm=None)
            self._calls = 0

        async def evaluate(self, state: PlanState, final_result: str) -> ExecutionCritique:
            self._calls += 1
            return _critique(need_replan=self._calls == 1)

    deps = RuntimeDependencies(
        planner=planner,
        tool_router=ToolSelectionRouter(registry),
        plan_executor=plan_executor,
        critic=FirstPassCritic(),
        replanner=ReplanningController(planner, validator),
        resolver=resolver,
        validator=validator,
    )
    runner = GraphRuntimeRunner(deps)
    result = await runner.invoke(USER_QUERY, session_id="graph-replan")

    assert result.replan_history
    assert result.replan_history[0].replanned is True
    critic_replan_traces = [
        t for t in result.execution_trace if t.recovery_action == "critic_replan"
    ]
    assert critic_replan_traces
    node_ids = [e.node_id for e in result.graph_trace if e.event == "node_start"]
    assert node_ids.count("replanner") >= 1
    assert node_ids.count("critic") >= 2


@pytest.mark.asyncio
async def test_graph_execute_api(async_client) -> None:
    response = await async_client.post(
        "/api/v1/graph_execute",
        json={"session_id": "api-graph", "query": USER_QUERY},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["runtime"] == "graph"
    assert body["plan"]["goal"]
    assert body["final_result"]
    assert len(body["graph_trace"]) > 0
    assert len(body["node_timeline"]) > 0


@pytest.mark.asyncio
async def test_graph_execute_streaming_api(async_client) -> None:
    response = await async_client.post(
        "/api/v1/graph_execute",
        json={"session_id": "api-graph-stream", "query": USER_QUERY, "stream": True},
    )
    assert response.status_code == 200
    text = response.text
    assert "graph_node" in text or "start" in text
    assert "done" in text
