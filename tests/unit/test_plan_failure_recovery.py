"""Unit tests for plan-level failure recovery."""

from __future__ import annotations

from typing import Any

import pytest

from agents.planner import PlannerAgent
from core.llm.rule_based import RuleBasedLLMClient
from plan.executor import PlanExecutor
from plan.failure_policy import FailurePolicy, PlanFailureConfig
from plan.state import PlanState
from plan.validator import PlanValidator
from schemas.plan import Plan, PlanStep, StepStatus
from tools.base import BaseTool
from tools.builtin.budget import budget_tool
from tools.builtin.weather import weather_tool
from tools.builtin.map import MapInput
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from tools.reliability import ToolReliabilityPolicy


class FlakyMapTool(BaseTool):
    name = "map"
    description = "Flaky map tool"
    input_schema = MapInput

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, args: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("map service unavailable")
        return {
            "origin": args.get("origin", "A"),
            "destination": args.get("destination", "B"),
            "mode": args.get("mode", "driving"),
            "distance_km": 10,
            "duration_min": 20,
            "steps": [],
            "source": "mock",
        }


class AlwaysFailMapTool(BaseTool):
    name = "map"
    description = "Always failing map"
    input_schema = MapInput

    async def run(self, args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("permanent map failure")


def _registry_with_map(map_tool: BaseTool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(weather_tool._tool_instance)
    registry.register(budget_tool._tool_instance)
    registry.register(map_tool)
    return registry


def _simple_plan() -> Plan:
    return Plan(
        goal="上海3日游",
        steps=[
            PlanStep(id=1, task="查天气", tool_hint="weather"),
            PlanStep(id=2, task="规划路线", tool_hint="map", dependency=[1]),
        ],
    )


@pytest.mark.asyncio
async def test_retry_policy_retries_failed_step() -> None:
    flaky = FlakyMapTool()
    registry = _registry_with_map(flaky)
    tool_executor = ToolExecutor(registry, reliability=ToolReliabilityPolicy(max_retries=0))
    plan_executor = PlanExecutor(
        tool_executor,
        failure_config=PlanFailureConfig(
            failure_policy=FailurePolicy.RETRY,
            step_max_retries=1,
        ),
    )

    state = PlanState.from_plan(_simple_plan())
    state.global_context.update({"city": "上海", "origin": "A", "destination": "B"})

    await plan_executor.execute(state.plan, state)

    assert flaky.calls == 2
    assert state.get_step_status(2) == StepStatus.COMPLETED
    failure_traces = [t for t in state.execution_trace if t.step_id == 2 and t.success is False]
    assert len(failure_traces) >= 1
    assert failure_traces[0].error is not None


@pytest.mark.asyncio
async def test_skip_policy_marks_failure_in_trace() -> None:
    registry = _registry_with_map(AlwaysFailMapTool())
    tool_executor = ToolExecutor(registry, reliability=ToolReliabilityPolicy(max_retries=0))
    plan_executor = PlanExecutor(
        tool_executor,
        failure_config=PlanFailureConfig(failure_policy=FailurePolicy.SKIP),
    )

    state = PlanState.from_plan(_simple_plan())
    state.global_context.update({"city": "上海", "origin": "A", "destination": "B"})

    await plan_executor.execute(state.plan, state)

    assert state.get_step_status(1) == StepStatus.COMPLETED
    assert state.get_step_status(2) == StepStatus.SKIPPED

    map_traces = [t for t in state.execution_trace if t.step_id == 2]
    assert any(t.success is False for t in map_traces)
    assert any(t.recovery_action == "skip" for t in map_traces)
    assert any(t.error for t in map_traces)


@pytest.mark.asyncio
async def test_replan_policy_rewrites_unfinished_steps() -> None:
    registry = _registry_with_map(AlwaysFailMapTool())
    tool_executor = ToolExecutor(registry, reliability=ToolReliabilityPolicy(max_retries=0))
    planner = PlannerAgent(RuleBasedLLMClient(), tool_registry=registry, max_retries=2)
    plan_executor = PlanExecutor(
        tool_executor,
        planner=planner,
        validator=PlanValidator(registry),
        failure_config=PlanFailureConfig(
            failure_policy=FailurePolicy.REPLAN,
            max_replan_attempts=1,
        ),
    )

    state = PlanState.from_plan(_simple_plan())
    state.global_context.update({"city": "上海", "origin": "A", "destination": "B", "days": 3})

    await plan_executor.execute(state.plan, state)

    assert state.get_step_status(1) == StepStatus.COMPLETED
    assert len(state.plan.steps) == 2
    assert state.plan.steps[-1].tool_hint == "budget"
    assert any(t.recovery_action == "replan" for t in state.execution_trace)
    assert "budget" in state.global_context.get("tool_outputs", {})

    replan_traces = [t for t in state.execution_trace if t.recovery_action == "replan"]
    assert replan_traces[0].success is False
    assert replan_traces[0].error
