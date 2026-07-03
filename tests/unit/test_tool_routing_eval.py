"""Unit tests for tool routing evaluation (Phase 9C)."""

from __future__ import annotations

import pytest

from eval.tool_eval.evaluator import ToolRoutingEvaluator
from eval.tool_eval.loader import load_tool_routing_dataset
from tools.adapters.mcp import MCPToolProvider
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
        return {"tool": tool_name}


@pytest.fixture
async def registry_with_mcp() -> ToolRegistry:
    registry = ToolRegistry.default()
    provider = MCPToolProvider(FakeMCPClient(), tool_prefix="mcp_")
    await provider.register_all(registry)
    return registry


def test_tool_routing_dataset_loads() -> None:
    cases, dataset_hash, paths = load_tool_routing_dataset(include_multi=True)
    assert len(cases) >= 15
    assert cases[0].id.startswith("tool-routing-")
    assert dataset_hash
    assert len(paths) >= 2


@pytest.mark.asyncio
async def test_tool_routing_evaluator_computes_accuracy(registry_with_mcp: ToolRegistry) -> None:
    cases, _, _ = load_tool_routing_dataset(include_multi=False)
    evaluator = ToolRoutingEvaluator(registry_with_mcp, mcp_enabled=True)
    report = evaluator.evaluate_cases(cases)
    assert report.total_cases >= 12
    assert 0.0 <= report.tool_selection_accuracy <= 1.0
    assert report.family_accuracy > 0.5
    assert len(report.per_case_results) == report.total_cases


@pytest.mark.asyncio
async def test_provider_accuracy(registry_with_mcp: ToolRegistry) -> None:
    cases, _, _ = load_tool_routing_dataset(include_multi=False)
    evaluator = ToolRoutingEvaluator(registry_with_mcp, mcp_enabled=True)
    report = evaluator.evaluate_cases(cases)
    assert report.provider_accuracy > 0.5
    mcp_cases = [r for r in report.per_case_results if r.selected_provider == "mcp"]
    assert report.mcp_usage_rate == len(mcp_cases) / report.total_cases


@pytest.mark.asyncio
async def test_fallback_rate(registry_with_mcp: ToolRegistry) -> None:
    cases, _, _ = load_tool_routing_dataset(include_multi=False)
    evaluator = ToolRoutingEvaluator(registry_with_mcp, mcp_enabled=True)
    report = evaluator.evaluate_cases(cases)
    assert report.fallback_rate >= 0.0
    failure_cases = [c for c in cases if c.simulate_mcp_failure]
    if failure_cases:
        assert report.fallback_rate > 0.0
        assert report.fallback_success_rate > 0.0
