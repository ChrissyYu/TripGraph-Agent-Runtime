"""Unit tests for multi-tool routing eval (Phase 9D)."""

from __future__ import annotations

import pytest

from eval.tool_eval.evaluator import ToolRoutingEvaluator
from eval.tool_eval.loader import load_tool_routing_dataset
from eval.tool_eval.models import ToolRoutingCase
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


def test_multi_tool_case_loads() -> None:
    cases, dataset_hash, paths = load_tool_routing_dataset(include_multi=True)
    multi = [c for c in cases if c.is_multi_tool]
    assert len(multi) >= 3
    assert dataset_hash
    assert len(paths) >= 2


@pytest.mark.asyncio
async def test_multi_tool_eval_computes_recall(registry_with_mcp: ToolRegistry) -> None:
    case = ToolRoutingCase.model_validate(
        {
            "id": "multi-test",
            "query": "MCP 上海3日游",
            "tasks": ["查询上海天气", "规划路线", "计算预算"],
            "expected_tools": ["mcp_weather", "mcp_map", "mcp_budget"],
            "expected_tool_families": ["weather", "map", "budget"],
            "expected_provider": "mcp",
            "policy_strategy": "mcp_first",
        },
    )
    evaluator = ToolRoutingEvaluator(registry_with_mcp, mcp_enabled=True)
    report = evaluator.evaluate_cases([case])
    result = report.per_case_results[0]
    assert result.is_multi_tool is True
    assert result.tool_recall == 1.0
    assert result.tool_precision == 1.0
    assert report.multi_tool_metrics is not None
    assert report.multi_tool_metrics.average_tool_recall == 1.0


@pytest.mark.asyncio
async def test_multi_tool_eval_provider_recall(registry_with_mcp: ToolRegistry) -> None:
    case = ToolRoutingCase.model_validate(
        {
            "id": "multi-builtin",
            "query": "北京旅行",
            "tasks": ["查询北京天气", "规划路线"],
            "expected_tools": ["weather", "map"],
            "expected_tool_families": ["weather", "map"],
            "expected_provider": "builtin",
            "policy_strategy": "builtin_first",
        },
    )
    evaluator = ToolRoutingEvaluator(registry_with_mcp, mcp_enabled=True)
    report = evaluator.evaluate_cases([case])
    result = report.per_case_results[0]
    assert result.provider_recall == 1.0
