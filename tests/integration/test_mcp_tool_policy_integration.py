"""Integration tests for MCP tool policy (Phase 9C)."""

from __future__ import annotations

from typing import Any

import pytest

from app.bootstrap import bootstrap_runtime
from config.settings import Settings, get_settings
from graph.runtime.execution_policy import ExecutionPolicy
from plan.executor import PlanExecutor
from plan.resolver import StepToolResolver
from plan.state import PlanState
from schemas.plan import Plan, PlanStep
from tools.adapters.mcp import MCPToolProvider
from tools.executor import ToolExecutor
from tools.policy.bootstrap import build_tool_policy_engine, build_tool_policy_tracer
from tools.registry import ToolRegistry
from tools.reliability import ToolReliabilityPolicy


class FakeMCPClient:
    async def list_tools(self):
        return [
            {
                "name": "mcp_weather",
                "description": "MCP weather",
                "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
        ]

    async def call_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if getattr(self, "_fail", False):
            raise RuntimeError("simulated MCP failure")
        return {"city": args.get("city"), "source": "mcp_mock"}


from tools.base import BaseTool
from tools.builtin.weather import WeatherInput


class FailingMCPWeatherTool(BaseTool):
    name = "mcp_weather"
    description = "failing mcp weather"
    input_schema = WeatherInput

    async def run(self, args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("simulated MCP weather failure")


@pytest.fixture
def registry_with_mcp() -> ToolRegistry:
    """Sync alias unused — kept for backward compat in file."""
    return ToolRegistry.default()


@pytest.mark.asyncio
async def test_mcp_enabled_policy_selects_mcp_weather(monkeypatch) -> None:
    monkeypatch.setenv("TOOL_POLICY_ENABLED", "true")
    monkeypatch.setenv("TOOL_POLICY_STRATEGY", "mcp_first")
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("EVAL_MODE", "real_llm_eval")
    get_settings.cache_clear()

    registry = ToolRegistry.default()
    provider = MCPToolProvider(FakeMCPClient(), tool_prefix="mcp_")
    await provider.register_all(registry)

    settings = Settings(
        tool_policy_enabled=True,
        tool_policy_strategy="mcp_first",
        mcp_enabled=True,
        eval_mode="real_llm_eval",
    )
    engine = build_tool_policy_engine(registry, settings)
    assert engine is not None
    decision = engine.decide(tool_hint="weather", task="查询上海天气", query="MCP 天气")
    assert decision.selected_tool == "mcp_weather"


@pytest.mark.asyncio
async def test_mcp_failure_fallback_to_builtin_weather(monkeypatch) -> None:
    monkeypatch.setenv("TOOL_POLICY_ENABLED", "true")
    monkeypatch.setenv("TOOL_POLICY_MCP_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("TOOL_POLICY_STRATEGY", "mcp_first")
    monkeypatch.setenv("EVAL_MODE", "real_llm_eval")
    get_settings.cache_clear()

    registry = ToolRegistry.default()
    registry.register(FailingMCPWeatherTool())

    settings = Settings(
        tool_policy_enabled=True,
        tool_policy_strategy="mcp_first",
        tool_policy_mcp_fallback_enabled=True,
        mcp_enabled=True,
        eval_mode="real_llm_eval",
    )
    engine = build_tool_policy_engine(registry, settings)
    tracer = build_tool_policy_tracer(settings)
    tool_executor = ToolExecutor(
        registry,
        reliability=ToolReliabilityPolicy(max_retries=0, timeout_sec=5.0),
    )
    plan_executor = PlanExecutor(
        tool_executor,
        resolver=StepToolResolver(),
        settings=settings,
        tool_policy_engine=engine,
        tool_policy_tracer=tracer,
    )

    decision = engine.decide(tool_hint="mcp_weather", task="查询上海天气")
    assert "weather" in decision.fallback_candidates

    plan = Plan(
        goal="weather",
        steps=[PlanStep(id=1, task="查询上海天气", tool_hint=decision.selected_tool or "mcp_weather")],
    )
    state = PlanState.from_plan(plan)
    state.global_context.update({
        "city": "上海",
        "tool_policy_decisions": {"1": decision.model_dump_json_safe()},
    })

    result_state = await plan_executor.execute(plan, state)
    trace = result_state.execution_trace
    assert any(entry.tool_name == "weather" and entry.success for entry in trace)
    assert any(entry.recovery_action == "mcp_to_builtin_fallback" for entry in trace)


@pytest.mark.asyncio
async def test_execution_trace_records_policy_fallback(monkeypatch) -> None:
    """Alias scenario: execution_trace must record policy fallback recovery_action."""
    monkeypatch.setenv("TOOL_POLICY_ENABLED", "true")
    monkeypatch.setenv("TOOL_POLICY_MCP_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("TOOL_POLICY_STRATEGY", "mcp_first")
    monkeypatch.setenv("EVAL_MODE", "real_llm_eval")
    get_settings.cache_clear()

    registry = ToolRegistry.default()
    registry.register(FailingMCPWeatherTool())

    settings = Settings(
        tool_policy_enabled=True,
        tool_policy_strategy="mcp_first",
        tool_policy_mcp_fallback_enabled=True,
        mcp_enabled=True,
        eval_mode="real_llm_eval",
    )
    engine = build_tool_policy_engine(registry, settings)
    tool_executor = ToolExecutor(
        registry,
        reliability=ToolReliabilityPolicy(max_retries=0, timeout_sec=5.0),
    )
    plan_executor = PlanExecutor(
        tool_executor,
        resolver=StepToolResolver(),
        settings=settings,
        tool_policy_engine=engine,
    )

    decision = engine.decide(tool_hint="mcp_weather", task="查询上海天气")
    plan = Plan(
        goal="weather",
        steps=[PlanStep(id=1, task="查询上海天气", tool_hint=decision.selected_tool or "mcp_weather")],
    )
    state = PlanState.from_plan(plan)
    state.global_context.update({
        "city": "上海",
        "tool_policy_decisions": {"1": decision.model_dump_json_safe()},
    })

    result = await plan_executor.execute(plan, state)
    assert any(e.recovery_action == "mcp_to_builtin_fallback" for e in result.execution_trace)


@pytest.mark.asyncio
async def test_mcp_disabled_mcp_first_fallbacks_builtin(monkeypatch) -> None:
    monkeypatch.setenv("TOOL_POLICY_ENABLED", "true")
    monkeypatch.setenv("TOOL_POLICY_STRATEGY", "mcp_first")
    monkeypatch.setenv("MCP_ENABLED", "false")
    monkeypatch.setenv("EVAL_MODE", "real_llm_eval")
    get_settings.cache_clear()

    registry = ToolRegistry.default()
    provider = MCPToolProvider(FakeMCPClient(), tool_prefix="mcp_")
    await provider.register_all(registry)

    settings = Settings(
        tool_policy_enabled=True,
        tool_policy_strategy="mcp_first",
        mcp_enabled=False,
        eval_mode="real_llm_eval",
    )
    engine = build_tool_policy_engine(registry, settings)
    assert engine is not None
    decision = engine.decide(tool_hint="weather", task="查询天气")
    assert decision.selected_tool == "weather"
    assert decision.selected_provider.value == "builtin"
