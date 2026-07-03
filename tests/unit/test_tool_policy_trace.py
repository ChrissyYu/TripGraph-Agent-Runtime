"""Unit tests for tool policy trace (Phase 9C)."""

from __future__ import annotations

import pytest

from graph.runtime.agent_state import AgentState
from graph.runtime.deps import RuntimeDependencies
from graph.runtime.nodes import router_node
from plan.state import PlanState
from schemas.plan import Plan, PlanStep
from tools.policy.engine import ToolPolicyEngine
from tools.policy.models import ToolPolicyDecision, ToolProvider
from tools.policy.trace import ToolPolicyTracer
from tools.registry import ToolRegistry
from unittest.mock import AsyncMock, MagicMock


def test_tool_policy_decision_serializable() -> None:
    decision = ToolPolicyDecision(
        original_tool_hint="weather",
        selected_tool="weather",
        selected_provider=ToolProvider.BUILTIN,
        reason="test",
        confidence=0.9,
    )
    payload = decision.model_dump_json_safe()
    assert payload["selected_provider"] == "builtin"
    assert payload["selected_tool"] == "weather"


@pytest.mark.asyncio
async def test_tool_policy_trace_added_to_state_observations() -> None:
    registry = ToolRegistry.default()
    engine = ToolPolicyEngine(registry, strategy="planner_hint_first", mcp_enabled=False)
    tracer = ToolPolicyTracer(trace_enabled=True)

    plan = Plan(
        goal="test",
        steps=[
            PlanStep(id=1, task="查询上海天气", tool_hint="weather"),
        ],
    )
    state = AgentState(session_id="t", query="查询上海天气")
    state.plan_state = PlanState.from_plan(plan, session_id="t")

    deps = RuntimeDependencies(
        planner=MagicMock(),
        tool_router=MagicMock(select=AsyncMock()),
        plan_executor=MagicMock(),
        critic=MagicMock(),
        replanner=MagicMock(),
        resolver=MagicMock(),
        validator=MagicMock(),
        tool_policy_engine=engine,
        tool_policy_tracer=tracer,
    )

    updated = await router_node(state, deps)
    assert "tool_policy_trace" in updated.observations
    assert len(updated.observations["tool_policy_trace"]) == 1
    entry = updated.observations["tool_policy_trace"][0]
    assert entry["selected_tool"] == "weather"
    assert updated.plan_state.global_context["tool_policy_decisions"]["1"]["selected_tool"] == "weather"
