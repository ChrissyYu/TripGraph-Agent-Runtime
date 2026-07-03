"""Unit tests for plan repair and replan robustness."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agents.planner import PlannerAgent
from agents.planner_prompt import build_planner_system_prompt, build_replan_system_prompt
from core.llm.base import LLMMessage
from core.llm.rule_based import RuleBasedLLMClient
from plan.repair import renumber_steps, repair_plan
from plan.replanning_controller import ReplanningController
from plan.state import PlanState
from plan.validator import PlanValidator
from schemas.execution_critic import ExecutionCritique
from schemas.plan import Plan, PlanStep, StepResult, StepStatus
from tools.registry import ToolRegistry


def test_plan_repair_renumbers_step_ids() -> None:
    steps = [
        PlanStep(id=2, task="查天气", tool_hint="weather"),
        PlanStep(id=3, task="算预算", tool_hint="budget", dependency=[2]),
        PlanStep(id=6, task="规划路线", tool_hint="map", dependency=[3]),
    ]
    repaired, id_map, notes = renumber_steps(steps)

    assert [step.id for step in repaired] == [1, 2, 3]
    assert id_map == {2: 1, 3: 2, 6: 3}
    assert notes


def test_plan_repair_remaps_dependencies() -> None:
    steps = [
        PlanStep(id=2, task="查天气", tool_hint="weather"),
        PlanStep(id=3, task="算预算", tool_hint="budget", dependency=[2]),
    ]
    repaired, _id_map, _notes = renumber_steps(steps)

    assert repaired[1].dependency == [1]


def test_remap_step_status_preserves_completed_steps_not_in_id_map() -> None:
    plan = Plan(
        goal="规划上海3日游并计算预算",
        steps=[
            PlanStep(id=1, task="计算预算", tool_hint="budget"),
            PlanStep(id=2, task="查询天气", tool_hint="weather"),
            PlanStep(id=3, task="规划路线", tool_hint="map"),
        ],
    )
    state = PlanState(plan)
    state.record_step_result(
        StepResult(
            step_id=2,
            task="查询天气",
            status=StepStatus.COMPLETED,
            tool_name="weather",
            observation={
                "city": "上海",
                "date": "today",
                "condition": "partly cloudy",
                "temp_c": 23,
            },
        ),
    )

    state.remap_step_status({7: 3})

    assert state.get_step_status(2) == StepStatus.COMPLETED
    assert state.step_results[2].tool_name == "weather"


def test_replanner_prompt_contains_continuous_id_constraints(registry: ToolRegistry) -> None:
    prompt = build_replan_system_prompt(registry)

    assert "continuous" in prompt.lower() or "continuous without gaps" in prompt.lower()
    assert "start at 1" in prompt.lower() or "starting at 1" in prompt.lower()
    assert "strict JSON" in prompt
    assert "markdown" in prompt.lower()
    assert "complete valid plan" in prompt.lower()


def test_planner_prompt_contains_tool_hint_guidance(registry: ToolRegistry) -> None:
    prompt = build_planner_system_prompt(registry)

    assert "tool_hint" in prompt
    assert "weather" in prompt
    assert "budget" in prompt
    assert "map" in prompt
    assert "Travel Planning Heuristics" in prompt
    assert "duplicate" in prompt.lower()


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry.default()


@pytest.mark.asyncio
async def test_replanner_validation_failure_attempts_repair_first(registry: ToolRegistry) -> None:
    class BadThenGoodLLM:
        async def complete(self, messages, **kwargs):
            return (
                '{"steps": ['
                '{"id": 2, "task": "计算预算", "tool_hint": "budget"},'
                '{"id": 3, "task": "规划路线", "tool_hint": "map"}'
                "]}"
            )

    state = PlanState.from_plan(
        Plan(
            goal="规划上海3日游并计算预算",
            steps=[
                PlanStep(id=1, task="查询上海天气", tool_hint="weather"),
                PlanStep(id=2, task="计算预算", tool_hint="budget", dependency=[1]),
            ],
        ),
    )
    state.set_step_status(1, StepStatus.COMPLETED)

    planner = PlannerAgent(BadThenGoodLLM(), tool_registry=registry)
    controller = ReplanningController(planner, PlanValidator(registry))
    critique = ExecutionCritique(
        score=0.4,
        critique="missing budget",
        need_replan=True,
        goal_completed=False,
        missing_info=["trip budget"],
    )

    outcome = await controller.handle(critique, state)

    assert outcome.result.replanned is True
    assert outcome.result.repair_applied is True
    report = PlanValidator(registry).validate(state.plan)
    assert report.success, report.errors


@pytest.mark.asyncio
async def test_replanner_validation_failure_falls_back_rulebased(registry: ToolRegistry) -> None:
    class InvalidLLM:
        async def complete(self, messages, **kwargs):
            return (
                '{"steps": ['
                '{"id": 9, "task": "无效工具步骤", "tool_hint": "not_a_tool"}'
                "]}"
            )

    planner = PlannerAgent(InvalidLLM(), tool_registry=registry)
    planner.rulebased_replan_from_critique = AsyncMock(
        side_effect=planner.rulebased_replan_from_critique,
    )

    state = PlanState.from_plan(
        Plan(
            goal="规划上海3日游并计算预算",
            steps=[PlanStep(id=1, task="查询上海天气", tool_hint="weather")],
        ),
    )
    state.set_step_status(1, StepStatus.FAILED)

    controller = ReplanningController(planner, PlanValidator(registry))
    critique = ExecutionCritique(
        score=0.2,
        critique="needs replan",
        need_replan=True,
        goal_completed=False,
        missing_info=["weather"],
    )

    outcome = await controller.handle(critique, state)

    assert outcome.result.replanned is True
    assert outcome.result.fallback_used is True
    planner.rulebased_replan_from_critique.assert_awaited_once()
    report = PlanValidator(registry).validate(state.plan)
    assert report.success, report.errors


def test_repair_plan_deduplicates_exact_duplicates() -> None:
    plan = Plan(
        goal="test",
        steps=[
            PlanStep(id=1, task="规划路线", tool_hint="map"),
            PlanStep(id=2, task="规划路线", tool_hint="map"),
            PlanStep(id=4, task="算预算", tool_hint="budget"),
        ],
    )
    result = repair_plan(plan)
    assert result.repaired
    assert len(result.plan.steps) == 2
    assert [step.id for step in result.plan.steps] == [1, 2]
