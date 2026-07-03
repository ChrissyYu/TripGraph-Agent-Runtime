"""Phase 9A.3: Qwen smoke stability — RuleBased fallback coverage and reporting."""

from __future__ import annotations

import json

import httpx
import pytest

from agents.planner import PlannerAgent
from core.llm.base import LLMMessage
from core.llm.fallback_trace import (
    LLMFallbackEvent,
    clear_fallback_events,
    planner_fallback_summary,
    record_fallback_event,
    timeout_suggestion,
)
from core.llm.rule_based import RuleBasedLLMClient
from plan.validator import PlanValidator
from scripts.smoke_qwen_reporting import build_planner_fallback_lines, collect_smoke_diagnostics
from tools.registry import ToolRegistry


TRIP_QUERY = "帮我规划北京5日游并计算预算"
SYSTEM_WITH_TOOLS = (
    "You are a travel planning assistant.\n"
    "Valid tool_hint values: weather, map, budget"
)


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry.default()


@pytest.mark.asyncio
async def test_rulebased_trip_budget_fallback_includes_weather_map_budget() -> None:
    client = RuleBasedLLMClient()
    raw = await client.complete(
        [
            LLMMessage(role="system", content=SYSTEM_WITH_TOOLS),
            LLMMessage(role="user", content=TRIP_QUERY),
        ],
        response_json=True,
    )
    plan = json.loads(raw)
    hints = [step["tool_hint"] for step in plan["steps"]]
    assert hints == ["weather", "map", "budget"]
    assert plan["steps"][0]["task"].startswith("查询北京")
    assert "路线" in plan["steps"][1]["task"]
    assert "预算" in plan["steps"][2]["task"]
    assert plan["steps"][1]["dependency"] == [1]
    assert plan["steps"][2]["dependency"] == [1, 2]


@pytest.mark.asyncio
async def test_rulebased_trip_budget_fallback_plan_valid(registry: ToolRegistry) -> None:
    planner = PlannerAgent(RuleBasedLLMClient(), tool_registry=registry)
    plan = await planner.create_plan(TRIP_QUERY)
    report = PlanValidator(registry).validate(plan)
    assert report.success, report.errors
    hints = [step.tool_hint for step in plan.steps if step.tool_hint]
    assert hints == ["weather", "map", "budget"]


def test_smoke_reports_planner_fallback_reason() -> None:
    clear_fallback_events()
    record_fallback_event(
        caller="planner",
        from_provider="qwen",
        reason="Request timed out after 60.0s",
        error=httpx.TimeoutException("timeout"),
    )
    summary = planner_fallback_summary()
    assert summary["planner_fallback_used"] is True
    assert summary["planner_error_type"] == "timeout"
    assert "timed out" in str(summary["planner_fallback_reason"]).lower()

    lines = build_planner_fallback_lines(timeout_sec=60.0)
    joined = "\n".join(lines)
    assert "planner_fallback_used: True" in joined
    assert "planner_error_type=timeout" in joined

    diagnostics = collect_smoke_diagnostics(
        "天气\n路线\n预算",
        timeout_sec=60.0,
        events=[
            LLMFallbackEvent(
                caller="planner",
                from_provider="qwen",
                reason="timeout",
                error_type="timeout",
            ),
        ],
    )
    assert diagnostics["planner_fallback_used"] is True
    assert diagnostics["planner_error_type"] == "timeout"


def test_smoke_timeout_suggestion() -> None:
    message = timeout_suggestion("timeout", 60.0)
    assert message is not None
    assert "QWEN_TIMEOUT_SEC=120" in message
    assert "180" in message

    lines = build_planner_fallback_lines(
        timeout_sec=60.0,
        events=[
            LLMFallbackEvent(
                caller="planner",
                from_provider="qwen",
                reason="timeout",
                error_type="timeout",
            ),
        ],
    )
    assert any("Suggestion:" in line and "QWEN_TIMEOUT_SEC=120" in line for line in lines)
    assert timeout_suggestion("timeout", 180.0) is None
    assert timeout_suggestion("api_error", 60.0) is None
