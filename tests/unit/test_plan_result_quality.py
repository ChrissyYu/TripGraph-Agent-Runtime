"""Tests for final result synthesis and plan normalization (Phase 9A.2)."""

from __future__ import annotations

import pytest

from plan.final_synthesis import check_final_result_coverage, synthesize_final_result
from plan.repair import normalize_plan
from plan.replanning_controller import ReplanningController
from plan.state import PlanState
from plan.validator import PlanValidator
from schemas.execution_critic import ExecutionCritique
from schemas.plan import Plan, PlanStep, StepResult, StepStatus
from plan.final_synthesis import check_final_result_coverage
from tools.registry import ToolRegistry


def _weather_obs(city: str = "上海") -> dict:
    return {"city": city, "date": "today", "condition": "cloudy", "temp_c": 17}


def _map_obs(origin: str, destination: str) -> dict:
    return {
        "origin": origin,
        "destination": destination,
        "duration_min": 30,
        "mode": "driving",
    }


def _budget_obs(total: float = 2450.0, days: int = 3) -> dict:
    return {
        "total": total,
        "currency": "CNY",
        "days": days,
        "breakdown": {"food": 300, "transport": 150},
    }


def _state_with_results() -> PlanState:
    plan = Plan(
        goal="规划上海3日游并计算预算",
        steps=[
            PlanStep(id=1, task="查天气", tool_hint="weather"),
            PlanStep(id=2, task="规划路线", tool_hint="map"),
            PlanStep(id=3, task="计算预算", tool_hint="budget"),
        ],
    )
    state = PlanState.from_plan(plan)
    state.global_context["city"] = "上海"
    state.global_context["days"] = 3
    state.record_step_result(
        StepResult(
            step_id=1,
            task="查天气",
            status=StepStatus.COMPLETED,
            tool_name="weather",
            observation=_weather_obs(),
        ),
    )
    state.record_step_result(
        StepResult(
            step_id=2,
            task="规划路线",
            status=StepStatus.COMPLETED,
            tool_name="map",
            observation=_map_obs("酒店", "外滩"),
        ),
    )
    state.record_step_result(
        StepResult(
            step_id=3,
            task="计算预算",
            status=StepStatus.COMPLETED,
            tool_name="budget",
            observation=_budget_obs(),
        ),
    )
    state.record_step_result(
        StepResult(
            step_id=99,
            task="重复预算",
            status=StepStatus.COMPLETED,
            tool_name="budget",
            observation=_budget_obs(),
        ),
    )
    return state


def test_finalize_synthesizes_weather_map_budget_outputs() -> None:
    state = _state_with_results()
    text = synthesize_final_result(state.plan, state)
    coverage = check_final_result_coverage(text)

    assert coverage["contains_weather_section"]
    assert coverage["contains_route_section"]
    assert coverage["contains_budget_section"]
    assert "上海" in text
    assert "酒店 → 外滩" in text
    assert "2450" in text


def test_finalize_deduplicates_repeated_budget_outputs() -> None:
    state = _state_with_results()
    text = synthesize_final_result(state.plan, state)
    assert text.count("2450") == 1


def test_plan_normalize_removes_duplicate_budget_steps() -> None:
    plan = Plan(
        goal="test",
        steps=[
            PlanStep(id=1, task="计算预算", tool_hint="budget"),
            PlanStep(id=2, task="重新计算旅行预算", tool_hint="budget"),
            PlanStep(id=3, task="查询天气", tool_hint="weather"),
        ],
    )
    result = normalize_plan(plan)
    budget_steps = [s for s in result.plan.steps if s.tool_hint == "budget"]
    assert len(budget_steps) == 1
    assert any(note for note in result.notes if "budget" in note.lower())


def test_plan_normalize_removes_final_synthesis_tool_step() -> None:
    plan = Plan(
        goal="test",
        steps=[
            PlanStep(id=1, task="综合生成完整行程计划", tool_hint="budget"),
        ],
    )
    result = normalize_plan(plan)
    assert result.plan.steps[0].tool_hint is None
    assert any("synthesis" in note.lower() or "Cleared tool_hint" in note for note in result.notes)


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry.default()


@pytest.mark.asyncio
async def test_replanner_preserves_completed_steps_on_merge(registry: ToolRegistry) -> None:
    class MutatingLLM:
        async def complete(self, messages, **kwargs):
            return (
                '{"steps": ['
                '{"id": 1, "task": "CHANGED", "tool_hint": "weather"},'
                '{"id": 2, "task": "新预算", "tool_hint": "budget"}'
                "]}"
            )

    state = PlanState.from_plan(
        Plan(
            goal="规划上海3日游并计算预算",
            steps=[
                PlanStep(id=1, task="查询上海天气", tool_hint="weather"),
                PlanStep(id=2, task="计算预算", tool_hint="budget"),
            ],
        ),
    )
    state.set_step_status(1, StepStatus.COMPLETED)

    planner = __import__("agents.planner", fromlist=["PlannerAgent"]).PlannerAgent(
        MutatingLLM(),
        tool_registry=registry,
    )
    controller = ReplanningController(planner, PlanValidator(registry))
    critique = ExecutionCritique(
        score=0.3,
        critique="needs replan",
        need_replan=True,
        goal_completed=False,
        missing_info=["budget"],
    )

    outcome = await controller.handle(critique, state)

    assert outcome.result.replanned is True
    assert state.plan.steps[0].task == "查询上海天气"
    assert state.get_step_status(1) == StepStatus.COMPLETED


def test_replanner_restore_completed_step_snapshots() -> None:
    original = PlanStep(id=1, task="查询上海天气", tool_hint="weather")
    state = PlanState.from_plan(
        Plan(
            goal="规划上海3日游并计算预算",
            steps=[
                original,
                PlanStep(id=2, task="计算预算", tool_hint="budget"),
            ],
        ),
    )
    state.plan.steps[0] = PlanStep(id=1, task="CHANGED", tool_hint="weather")
    warnings = state.restore_completed_step_snapshots({1: original})

    assert warnings
    assert state.plan.steps[0].task == "查询上海天气"


def test_replanner_history_records_completed_step_override(registry: ToolRegistry) -> None:
    state = PlanState.from_plan(
        Plan(
            goal="规划上海3日游并计算预算",
            steps=[PlanStep(id=1, task="查询上海天气", tool_hint="weather")],
        ),
    )
    snapshot = {1: state.plan.steps[0].model_copy(deep=True)}
    state.plan.steps[0] = PlanStep(id=1, task="CHANGED", tool_hint="weather")
    overrides = state.restore_completed_step_snapshots(snapshot)
    assert overrides
    assert "immutable completed step" in overrides[0]


def test_smoke_reports_final_result_coverage() -> None:
    text = synthesize_final_result(_state_with_results().plan, _state_with_results())
    coverage = check_final_result_coverage(text)
    assert coverage["contains_weather_section"]
    assert coverage["contains_route_section"]
    assert coverage["contains_budget_section"]
