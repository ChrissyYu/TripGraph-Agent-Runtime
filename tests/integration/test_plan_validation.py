"""Integration: invalid plans must not reach PlanExecutor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import PlanValidationError
from plan.orchestrator import PlanOrchestrator
from plan.validator import PlanValidator
from schemas.plan import Plan, PlanStep


@pytest.mark.asyncio
async def test_invalid_plan_blocks_executor() -> None:
    invalid_plan = Plan(
        goal="test",
        steps=[
            PlanStep(id=1, task="a", tool_hint="nonexistent_tool"),
        ],
    )

    planner = AsyncMock()
    planner.create_plan.return_value = invalid_plan

    tool_executor = MagicMock()
    tool_executor.registry = __import__(
        "tools.registry", fromlist=["ToolRegistry"]
    ).ToolRegistry.default()
    tool_executor.export_trace_json.return_value = "{}"

    plan_executor = AsyncMock()
    orchestrator = PlanOrchestrator(
        planner=planner,
        tool_executor=tool_executor,
        plan_executor=plan_executor,
        validator=PlanValidator(tool_executor.registry),
    )

    with pytest.raises(PlanValidationError) as exc_info:
        await orchestrator.run("test query")

    assert "nonexistent_tool" in str(exc_info.value).lower() or any(
        "nonexistent_tool" in e for e in exc_info.value.errors
    )
    plan_executor.execute.assert_not_called()


@pytest.mark.asyncio
async def test_plan_execute_api_returns_422_on_invalid_plan(app, async_client) -> None:
    invalid_plan = Plan(
        goal="test",
        steps=[PlanStep(id=1, task="x", tool_hint="invalid_tool")],
    )

    app.state.plan_orchestrator._planner.create_plan = AsyncMock(return_value=invalid_plan)

    response = await async_client.post(
        "/api/v1/plan_execute",
        json={"session_id": "bad-plan", "query": "test"},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "validation failed" in detail["message"].lower()
    assert detail["validation"]["success"] is False
    assert detail["validation"]["errors"]
