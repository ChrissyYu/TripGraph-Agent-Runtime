"""Integration test: plan-driven agent full loop."""

from __future__ import annotations

import json

import pytest

from agents.planner import PlannerAgent
from core.llm.rule_based import RuleBasedLLMClient
from plan.orchestrator import PlanOrchestrator
from schemas.plan import StepStatus
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from tools.reliability import ToolReliabilityPolicy

USER_QUERY = "规划上海3日游并计算预算"


@pytest.fixture
def plan_orchestrator() -> PlanOrchestrator:
    registry = ToolRegistry.default()
    tool_executor = ToolExecutor(
        registry,
        reliability=ToolReliabilityPolicy(max_retries=0),
    )
    planner = PlannerAgent(RuleBasedLLMClient(), tool_registry=registry, max_retries=2)
    return PlanOrchestrator(
        planner=planner,
        tool_executor=tool_executor,
    )


@pytest.mark.asyncio
async def test_plan_driven_agent_full_loop(plan_orchestrator: PlanOrchestrator) -> None:
    result = await plan_orchestrator.run(USER_QUERY, session_id="shanghai-trip")

    # --- plan generated ---
    assert result.plan.goal
    assert len(result.plan.steps) >= 3
    step_ids = [s.id for s in result.plan.steps]
    assert step_ids == sorted(step_ids)
    tool_hints = [s.tool_hint for s in result.plan.steps if s.tool_hint]
    assert "weather" in tool_hints
    assert "budget" in tool_hints

    # --- steps executed ---
    assert len(result.execution_trace) == len(result.plan.steps)
    assert all(entry.success is True for entry in result.execution_trace)
    assert all(entry.status == StepStatus.COMPLETED for entry in result.execution_trace)

    # --- tools invoked (via trace) ---
    tool_trace = json.loads(result.tool_trace_json)
    tool_names = [r["tool_name"] for r in tool_trace["records"] if not r["tool_name"].startswith("__")]
    assert "weather" in tool_names
    assert "budget" in tool_names

    # --- state updated ---
    assert result.state_summary["completed_steps"]
    assert len(result.state_summary["completed_steps"]) == len(result.plan.steps)
    assert result.state_summary["global_context"].get("city") == "上海"
    assert result.state_summary["global_context"].get("days") == 3
    assert "tool_outputs" in result.state_summary["global_context"]
    assert "weather" in result.state_summary["global_context"]["tool_outputs"]
    assert "budget" in result.state_summary["global_context"]["tool_outputs"]

    # --- final answer ---
    assert result.final_result
    assert "上海" in result.final_result
    assert "预算" in result.final_result

    # --- execution critic ---
    assert result.execution_critique is not None
    assert 0.0 <= result.execution_critique.score <= 1.0
    assert result.execution_critique.critique
    assert result.execution_critique.goal_completed is True


@pytest.mark.asyncio
async def test_plan_execute_api_endpoint(async_client) -> None:
    response = await async_client.post(
        "/api/v1/plan_execute",
        json={"session_id": "api-trip", "query": USER_QUERY},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "api-trip"
    assert body["plan"]["goal"]
    assert len(body["execution_trace"]) >= 3
    assert body["final_result"]
    assert "tool_trace_json" in body
    trace = json.loads(body["tool_trace_json"])
    assert trace["record_count"] >= 2


@pytest.mark.asyncio
async def test_planner_retry_on_invalid_json() -> None:
    from core.llm.base import LLMMessage

    class FlakyLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(
            self,
            messages: list[LLMMessage],
            *,
            temperature: float = 0.2,
            response_json: bool = False,
        ) -> str:
            self.calls += 1
            if self.calls == 1:
                return "not valid json {{"
            return json.dumps(
                {
                    "goal": "test",
                    "steps": [{"id": 1, "task": "查天气", "tool_hint": "weather"}],
                },
                ensure_ascii=False,
            )

    llm = FlakyLLM()
    planner = PlannerAgent(llm, tool_registry=ToolRegistry.default(), max_retries=2)
    plan = await planner.create_plan(USER_QUERY)
    assert plan.steps
    assert llm.calls == 2
