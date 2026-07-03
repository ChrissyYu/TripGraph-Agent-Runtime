"""Unit tests for tool selection router."""

from __future__ import annotations

import pytest

from schemas.tool_router import ToolRouterStrategy
from tools.registry import ToolRegistry
from tools.router import ToolSelectionRouter


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry.default()


@pytest.mark.asyncio
async def test_rule_based_selects_weather(registry: ToolRegistry) -> None:
    router = ToolSelectionRouter(registry, strategy=ToolRouterStrategy.RULE_BASED)
    result = await router.select("查询上海未来三天天气")

    assert result.best_tool == "weather"
    assert result.confidence > 0
    assert result.strategy == ToolRouterStrategy.RULE_BASED
    assert all(alt.tool != result.best_tool for alt in result.alternatives)


@pytest.mark.asyncio
async def test_rule_based_selects_budget(registry: ToolRegistry) -> None:
    router = ToolSelectionRouter(registry, strategy=ToolRouterStrategy.RULE_BASED)
    result = await router.select("计算7天旅行预算和总花费")

    assert result.best_tool == "budget"
    assert result.confidence > 0


@pytest.mark.asyncio
async def test_rule_based_selects_map(registry: ToolRegistry) -> None:
    router = ToolSelectionRouter(registry, strategy=ToolRouterStrategy.RULE_BASED)
    result = await router.select("规划从上海站到外滩的公交路线")

    assert result.best_tool == "map"
    assert result.confidence > 0


@pytest.mark.asyncio
async def test_embedding_strategy_returns_tool(registry: ToolRegistry) -> None:
    router = ToolSelectionRouter(registry, strategy=ToolRouterStrategy.EMBEDDING)
    result = await router.select("Get weather forecast for Tokyo")

    assert result.best_tool == "weather"
    assert result.confidence > 0
    assert result.strategy == ToolRouterStrategy.EMBEDDING


def test_embedding_select_sync(registry: ToolRegistry) -> None:
    router = ToolSelectionRouter(registry, strategy=ToolRouterStrategy.EMBEDDING)
    result = router.select_sync("Calculate total trip budget for 5 days")

    assert result.best_tool == "budget"
    assert result.strategy == ToolRouterStrategy.EMBEDDING


@pytest.mark.asyncio
async def test_llm_strategy_returns_tool(registry: ToolRegistry) -> None:
    router = ToolSelectionRouter(registry, strategy=ToolRouterStrategy.LLM)
    result = await router.select("估算3天旅行预算")

    assert result.best_tool == "budget"
    assert 0.0 <= result.confidence <= 1.0
    assert result.strategy == ToolRouterStrategy.LLM


@pytest.mark.asyncio
async def test_no_match_returns_none(registry: ToolRegistry) -> None:
    router = ToolSelectionRouter(registry, strategy=ToolRouterStrategy.RULE_BASED)
    result = await router.select("写一首关于春天的诗")

    assert result.best_tool is None
    assert result.confidence == 0.0
    assert result.alternatives == []


@pytest.mark.asyncio
async def test_alternatives_exclude_best_tool(registry: ToolRegistry) -> None:
    router = ToolSelectionRouter(registry, strategy=ToolRouterStrategy.RULE_BASED)
    result = await router.select("查询天气并估算旅行预算")

    assert result.best_tool in {"weather", "budget"}
    assert all(alt.tool != result.best_tool for alt in result.alternatives)
