"""Unit tests for PlanValidator."""

from __future__ import annotations

import pytest

from core.exceptions import PlanValidationError
from plan.validator import PlanValidator
from schemas.plan import Plan, PlanStep
from tools.registry import ToolRegistry


@pytest.fixture
def validator() -> PlanValidator:
    return PlanValidator(ToolRegistry.default())


def _plan(**overrides) -> Plan:
    base = Plan(
        goal="上海3日游",
        steps=[
            PlanStep(id=1, task="查天气", tool_hint="weather"),
            PlanStep(id=2, task="算预算", tool_hint="budget", dependency=[1]),
        ],
    )
    if overrides:
        return Plan.model_validate({**base.model_dump(), **overrides})
    return base


def test_valid_plan_passes(validator: PlanValidator) -> None:
    report = validator.validate(_plan())
    assert report.success is True
    assert report.errors == []


def test_empty_goal_fails(validator: PlanValidator) -> None:
    report = validator.validate(_plan(goal="  "))
    assert report.success is False
    assert any("goal" in e for e in report.errors)


def test_empty_steps_fails(validator: PlanValidator) -> None:
    report = validator.validate(_plan(steps=[]))
    assert report.success is False
    assert any("at least one step" in e for e in report.errors)


def test_non_continuous_step_ids(validator: PlanValidator) -> None:
    plan = Plan(
        goal="test",
        steps=[
            PlanStep(id=1, task="a", tool_hint="weather"),
            PlanStep(id=3, task="b", tool_hint="budget"),
        ],
    )
    report = validator.validate(plan)
    assert report.success is False
    assert any("continuous" in e for e in report.errors)


def test_duplicate_step_ids(validator: PlanValidator) -> None:
    plan = Plan(
        goal="test",
        steps=[
            PlanStep(id=1, task="a"),
            PlanStep(id=1, task="b"),
        ],
    )
    report = validator.validate(plan)
    assert report.success is False
    assert any("Duplicate" in e for e in report.errors)


def test_dependency_cycle_detected(validator: PlanValidator) -> None:
    plan = Plan(
        goal="test",
        steps=[
            PlanStep(id=1, task="a", dependency=[2]),
            PlanStep(id=2, task="b", dependency=[1]),
        ],
    )
    report = validator.validate(plan)
    assert report.success is False
    assert any("cycle" in e.lower() for e in report.errors)


def test_unknown_dependency(validator: PlanValidator) -> None:
    plan = Plan(
        goal="test",
        steps=[PlanStep(id=1, task="a", dependency=[99])],
    )
    report = validator.validate(plan)
    assert report.success is False
    assert any("unknown step" in e for e in report.errors)


def test_unknown_tool_hint(validator: PlanValidator) -> None:
    plan = Plan(
        goal="test",
        steps=[PlanStep(id=1, task="a", tool_hint="flight_search")],
    )
    report = validator.validate(plan)
    assert report.success is False
    assert any("flight_search" in e for e in report.errors)
    assert any("Available tools" in e for e in report.errors)


def test_validate_raw_invalid_json(validator: PlanValidator) -> None:
    report = validator.validate_raw("{bad json")
    assert report.success is False
    assert any("JSON structure" in e for e in report.errors)


def test_assert_valid_raises(validator: PlanValidator) -> None:
    with pytest.raises(PlanValidationError) as exc_info:
        validator.assert_valid(_plan(steps=[]))
    assert exc_info.value.errors


def test_readable_message(validator: PlanValidator) -> None:
    report = validator.validate(_plan(steps=[]))
    message = report.readable_message()
    assert "validation failed" in message.lower()
    assert "-" in message
