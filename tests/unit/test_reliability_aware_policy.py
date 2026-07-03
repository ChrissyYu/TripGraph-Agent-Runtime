"""Unit tests for reliability_aware policy (Phase 9D)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config.settings import Settings
from tools.policy.engine import ToolPolicyEngine
from tools.policy.models import ToolPolicyStrategy, ToolProvider
from tools.policy.reliability import (
    ToolReliabilityStats,
    load_reliability_stats,
    score_tool_provider,
)
from tools.registry import ToolRegistry


@pytest.fixture
def stats_file(tmp_path: Path) -> Path:
    payload = {
        "weather": {
            "builtin": {"success_rate": 0.98, "avg_latency_ms": 20, "fallback_rate": 0.01},
            "mcp": {"success_rate": 0.90, "avg_latency_ms": 80, "fallback_rate": 0.10},
        },
        "map": {
            "builtin": {"success_rate": 0.80, "avg_latency_ms": 30, "fallback_rate": 0.05},
            "mcp": {"success_rate": 0.95, "avg_latency_ms": 70, "fallback_rate": 0.02},
        },
        "budget": {
            "builtin": {"success_rate": 0.99, "avg_latency_ms": 10, "fallback_rate": 0.00},
            "mcp": {"success_rate": 0.93, "avg_latency_ms": 50, "fallback_rate": 0.03},
        },
    }
    path = tmp_path / "stats.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def registry_with_mcp() -> ToolRegistry:
    from tools.base import BaseTool
    from tools.builtin.budget import BudgetInput
    from tools.builtin.map import MapInput
    from tools.builtin.weather import WeatherInput

    class MCPStub(BaseTool):
        def __init__(self, name: str, schema: type) -> None:
            self.name = name
            self.description = name
            self.input_schema = schema

        async def run(self, args: dict):
            return {"tool": self.name}

    registry = ToolRegistry.default()
    registry.register(MCPStub("mcp_weather", WeatherInput))
    registry.register(MCPStub("mcp_map", MapInput))
    registry.register(MCPStub("mcp_budget", BudgetInput))
    return registry


def test_reliability_aware_selects_higher_score_provider(
    stats_file: Path,
    registry_with_mcp: ToolRegistry,
) -> None:
    registry = registry_with_mcp
    settings = Settings(
        tool_policy_reliability_stats_path=str(stats_file),
        eval_mode="real_llm_eval",
    )
    engine = ToolPolicyEngine(
        registry,
        strategy=ToolPolicyStrategy.RELIABILITY_AWARE,
        mcp_enabled=True,
        settings=settings,
    )
    decision = engine.decide(tool_hint="map", task="规划上海路线", query="规划路线")
    assert decision.selected_tool == "mcp_map"
    assert decision.selected_provider == ToolProvider.MCP
    assert "reliability_aware" in decision.reason


def test_reliability_aware_falls_back_when_stats_missing(tmp_path: Path) -> None:
    registry = ToolRegistry.default()
    settings = Settings(
        tool_policy_reliability_stats_path=str(tmp_path / "missing.json"),
        eval_mode="real_llm_eval",
    )
    engine = ToolPolicyEngine(
        registry,
        strategy=ToolPolicyStrategy.RELIABILITY_AWARE,
        settings=settings,
    )
    decision = engine.decide(tool_hint="weather", task="查询天气")
    assert decision.selected_tool == "weather"
    assert "stats_missing" in decision.reason


def test_reliability_score_penalizes_latency(stats_file: Path) -> None:
    stats = load_reliability_stats(stats_file)
    low_latency = score_tool_provider("weather", "builtin", stats)
    high_latency = score_tool_provider("weather", "mcp", stats)
    assert low_latency is not None and high_latency is not None
    assert low_latency.score > high_latency.score


def test_reliability_score_penalizes_fallback_rate() -> None:
    from tools.policy.reliability import ToolProviderReliability, ToolReliabilityStats

    payload = ToolReliabilityStats(
        families={
            "budget": {
                "a": ToolProviderReliability(success_rate=0.9, avg_latency_ms=10, fallback_rate=0.0),
                "b": ToolProviderReliability(success_rate=0.9, avg_latency_ms=10, fallback_rate=0.2),
            },
        },
    )
    score_a = score_tool_provider("budget", "a", payload)
    score_b = score_tool_provider("budget", "b", payload)
    assert score_a is not None and score_b is not None
    assert score_a.score > score_b.score


def test_decision_reason_contains_reliability_scores(
    stats_file: Path,
    registry_with_mcp: ToolRegistry,
) -> None:
    registry = registry_with_mcp
    settings = Settings(
        tool_policy_reliability_stats_path=str(stats_file),
        eval_mode="real_llm_eval",
    )
    engine = ToolPolicyEngine(
        registry,
        strategy=ToolPolicyStrategy.RELIABILITY_AWARE,
        settings=settings,
    )
    decision = engine.decide(tool_hint="budget", task="计算预算")
    assert "score=" in decision.reason
    assert decision.fallback_candidates
