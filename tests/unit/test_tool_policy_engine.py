"""Unit tests for ToolPolicyEngine (Phase 9C)."""

from __future__ import annotations

import pytest

from tools.adapters.mcp import MCPToolProvider
from tools.policy.engine import ToolPolicyEngine
from tools.policy.models import ToolFamily, ToolPolicyStrategy, ToolProvider, tool_family, tool_provider
from tools.registry import ToolRegistry


class FakeMCPClient:
    async def list_tools(self):
        return [
            {
                "name": "mcp_weather",
                "description": "MCP weather",
                "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
            {
                "name": "mcp_map",
                "description": "MCP map",
                "input_schema": {"type": "object", "properties": {"destination": {"type": "string"}}},
            },
            {
                "name": "mcp_budget",
                "description": "MCP budget",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}, "days": {"type": "integer"}},
                },
            },
        ]

    async def call_tool(self, tool_name: str, args: dict):
        return {"tool": tool_name, "source": "fake_mcp"}


@pytest.fixture
async def registry_with_mcp() -> ToolRegistry:
    registry = ToolRegistry.default()
    provider = MCPToolProvider(FakeMCPClient(), tool_prefix="mcp_")
    await provider.register_all(registry)
    return registry


def test_family_mapping_builtin_and_mcp() -> None:
    assert tool_family("weather") == ToolFamily.WEATHER
    assert tool_family("mcp_weather") == ToolFamily.WEATHER
    assert tool_provider("weather") == ToolProvider.BUILTIN
    assert tool_provider("mcp_map") == ToolProvider.MCP


@pytest.mark.asyncio
async def test_planner_hint_first_respects_mcp_hint(registry_with_mcp: ToolRegistry) -> None:
    engine = ToolPolicyEngine(
        registry_with_mcp,
        strategy=ToolPolicyStrategy.PLANNER_HINT_FIRST,
        mcp_enabled=True,
    )
    decision = engine.decide(tool_hint="mcp_weather", task="查询天气")
    assert decision.selected_tool == "mcp_weather"
    assert decision.selected_provider == ToolProvider.MCP
    assert decision.policy_name == "planner_hint_first"


@pytest.mark.asyncio
async def test_mcp_first_maps_builtin_hint_to_mcp_tool(registry_with_mcp: ToolRegistry) -> None:
    engine = ToolPolicyEngine(
        registry_with_mcp,
        strategy=ToolPolicyStrategy.MCP_FIRST,
        mcp_enabled=True,
    )
    decision = engine.decide(tool_hint="weather", task="查询天气")
    assert decision.selected_tool == "mcp_weather"
    assert "weather" in decision.fallback_candidates


@pytest.mark.asyncio
async def test_builtin_first_maps_mcp_hint_to_builtin_tool(registry_with_mcp: ToolRegistry) -> None:
    engine = ToolPolicyEngine(
        registry_with_mcp,
        strategy=ToolPolicyStrategy.BUILTIN_FIRST,
        mcp_enabled=True,
    )
    decision = engine.decide(tool_hint="mcp_weather", task="查询天气")
    assert decision.selected_tool == "weather"
    assert "mcp_weather" in decision.fallback_candidates


def test_mcp_first_fallbacks_to_builtin_when_mcp_unavailable() -> None:
    registry = ToolRegistry.default()
    engine = ToolPolicyEngine(
        registry,
        strategy=ToolPolicyStrategy.MCP_FIRST,
        mcp_enabled=False,
    )
    decision = engine.decide(tool_hint="weather", task="查询天气")
    assert decision.selected_tool == "weather"
    assert decision.selected_provider == ToolProvider.BUILTIN
    assert "MCP disabled" in decision.reason or decision.reason


@pytest.mark.asyncio
async def test_deterministic_policy_uses_builtin(registry_with_mcp: ToolRegistry) -> None:
    engine = ToolPolicyEngine(
        registry_with_mcp,
        strategy=ToolPolicyStrategy.DETERMINISTIC,
        mcp_enabled=True,
    )
    decision = engine.decide(tool_hint="mcp_weather", task="查询天气")
    assert decision.selected_tool == "weather"
    assert decision.policy_name == "builtin_first"
