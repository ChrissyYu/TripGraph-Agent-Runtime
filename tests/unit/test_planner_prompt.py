"""Unit tests for planner prompt and tool registry injection."""

from __future__ import annotations

import pytest

from agents.planner import PlannerAgent
from agents.planner_prompt import (
    build_planner_system_prompt,
    build_replan_system_prompt,
    format_tool_registry_context,
)
from core.llm.rule_based import RuleBasedLLMClient
from plan.validator import PlanValidator
from tools.registry import ToolRegistry


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry.default()


def test_tool_registry_context_lists_names_and_descriptions(registry: ToolRegistry) -> None:
    context = format_tool_registry_context(registry)

    assert "**weather**:" in context
    assert "Get weather forecast" in context
    assert "**map**:" in context
    assert "Plan a route" in context
    assert "**budget**:" in context
    assert "Calculate total trip budget" in context
    assert "Parameters:" in context
    assert "Valid tool_hint values:" in context
    for name in registry.list_names():
        assert name in context


def test_planner_system_prompt_injects_tool_registry(registry: ToolRegistry) -> None:
    prompt = build_planner_system_prompt(registry)

    assert "Minimum steps" in prompt
    assert "tool_hint accuracy" in prompt or "tool_hint MUST" in prompt
    assert "Complex tasks" in prompt or "decompose" in prompt
    assert "Tool Registry" in prompt
    assert "weather" in prompt
    assert "budget" in prompt


def test_replan_system_prompt_injects_tool_registry(registry: ToolRegistry) -> None:
    prompt = build_replan_system_prompt(registry)

    assert "Replan Rules" in prompt
    assert "Tool Registry" in prompt
    assert "Valid tool_hint values:" in prompt


@pytest.mark.asyncio
async def test_planner_generates_valid_tool_hints(registry: ToolRegistry) -> None:
    planner = PlannerAgent(RuleBasedLLMClient(), tool_registry=registry)
    plan = await planner.create_plan("规划上海3日游并计算预算")

    validator = PlanValidator(registry)
    report = validator.validate(plan)
    assert report.success, report.errors

    tool_hints = {step.tool_hint for step in plan.steps if step.tool_hint}
    assert tool_hints <= set(registry.list_names())


@pytest.mark.asyncio
async def test_planner_decomposes_complex_dual_city_query(registry: ToolRegistry) -> None:
    planner = PlannerAgent(RuleBasedLLMClient(), tool_registry=registry)
    plan = await planner.create_plan("规划上海北京双城7日游并对比天气和预算")

    assert len(plan.steps) >= 4
    tool_hints = [step.tool_hint for step in plan.steps if step.tool_hint]
    assert tool_hints.count("weather") >= 2
    assert "budget" in tool_hints

    report = PlanValidator(registry).validate(plan)
    assert report.success, report.errors


@pytest.mark.asyncio
async def test_planner_retry_includes_available_tools(registry: ToolRegistry) -> None:
    from core.llm.base import LLMMessage

    captured: list[list[LLMMessage]] = []

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
            captured.append(list(messages))
            if self.calls == 1:
                return "not json"
            import json

            return json.dumps(
                {
                    "goal": "test",
                    "steps": [{"id": 1, "task": "查天气", "tool_hint": "weather"}],
                },
                ensure_ascii=False,
            )

    planner = PlannerAgent(FlakyLLM(), tool_registry=registry, max_retries=2)
    await planner.create_plan("test query")

    retry_msg = captured[1][-1].content
    assert "Available tools:" in retry_msg
    assert "weather" in retry_msg
