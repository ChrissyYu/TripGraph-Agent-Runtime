"""Unit tests for graph demo eval scorer."""

from __future__ import annotations

import pytest

from eval.graph_eval.diagnostics import build_low_recall_diagnostics
from eval.graph_eval.models import GraphDemoEvalCase, GraphDemoEvalResult
from eval.graph_eval.scorer import (
    GraphDemoScorer,
    extract_final_sections,
    final_section_coverage,
    provider_precision,
    provider_recall,
    set_precision,
    set_recall,
)


def test_tool_family_recall() -> None:
    assert set_recall(["weather", "map"], ["weather", "map", "budget"]) == 1.0
    assert set_recall(["weather"], ["map"]) == 0.0
    assert set_recall([], ["weather"]) is None


def test_tool_family_precision() -> None:
    assert set_precision(["weather"], ["weather", "map", "budget"]) == pytest.approx(1 / 3)
    assert set_precision(["weather", "map"], ["weather", "map", "budget"]) == pytest.approx(2 / 3)


def test_tool_selection_recall() -> None:
    assert set_recall(["weather", "map"], ["weather", "map", "budget"]) == 1.0
    assert set_recall(["mcp_weather"], ["weather"]) == 0.0


def test_tool_selection_precision() -> None:
    assert set_precision(["mcp_weather"], ["weather", "map", "budget"]) == 0.0
    assert set_precision(["weather"], ["weather", "map", "budget"]) == pytest.approx(1 / 3)


def test_provider_recall() -> None:
    assert provider_recall(["mcp"], ["mcp", "mcp", "mcp"]) == 1.0
    assert provider_recall(["builtin"], ["mcp", "builtin"]) == 1.0
    assert provider_recall(["mcp"], ["builtin", "builtin"]) == 0.0
    assert provider_recall(None, ["builtin"]) is None


def test_provider_precision() -> None:
    assert provider_precision(["mcp"], ["mcp", "mcp", "mcp"]) == 1.0
    assert provider_precision(["builtin"], ["mcp", "builtin"]) == 0.5
    assert provider_precision(["mcp"], ["builtin", "builtin"]) == 0.0


def test_final_section_coverage() -> None:
    text = "目标：上海\n天气信息：\n- 晴\n总结：已完成规划。"
    assert final_section_coverage(["天气信息", "总结"], text) == 1.0
    assert final_section_coverage(["预算估算"], text) == 0.0
    sections = extract_final_sections(text)
    assert "天气信息" in sections
    assert "总结" in sections


def test_low_recall_diagnostics() -> None:
    case = GraphDemoEvalCase(
        id="x",
        query="使用 MCP 查询上海天气",
        expected_tools=["mcp_weather"],
        expected_providers=["mcp"],
        mcp_enabled=True,
    )
    result = GraphDemoEvalResult(
        id="x",
        query=case.query,
        expected_tools=["mcp_weather"],
        actual_tools=["weather", "map", "budget"],
        expected_providers=["mcp"],
        actual_providers=["builtin", "builtin", "builtin"],
        tool_selection_recall=0.0,
        provider_recall=0.0,
        tool_selection_precision=0.0,
        provider_precision=0.0,
    )
    low_tool, low_provider = build_low_recall_diagnostics([case], [result])
    assert len(low_tool) == 1
    assert len(low_provider) == 1
    assert "mcp_weather" in low_tool[0].mismatch_reason
    assert "RuleBased" in low_tool[0].mismatch_reason


def test_aggregate_metrics() -> None:
    scorer = GraphDemoScorer()
    results = [
        GraphDemoEvalResult(
            id="a",
            query="q1",
            execution_success=True,
            tool_family_recall=1.0,
            tool_family_precision=1.0,
            tool_selection_recall=1.0,
            tool_selection_precision=1.0,
            provider_recall=1.0,
            provider_precision=1.0,
            final_section_coverage=1.0,
            latency_ms=10.0,
        ),
        GraphDemoEvalResult(
            id="b",
            query="q2",
            execution_success=False,
            tool_family_recall=0.5,
            tool_family_precision=0.5,
            tool_selection_recall=None,
            provider_recall=0.0,
            provider_precision=0.0,
            final_section_coverage=0.5,
            latency_ms=30.0,
            error_type="RuntimeError",
        ),
    ]
    agg = scorer.aggregate(results)
    assert agg.total_cases == 2
    assert agg.execution_success_rate == 0.5
    assert agg.avg_tool_family_recall == 0.75
    assert agg.avg_tool_selection_recall == 1.0
    assert agg.avg_provider_recall == 0.5
    assert agg.avg_provider_precision == 0.5
    assert agg.avg_final_section_coverage == 0.75
    assert agg.avg_latency_ms == 20.0
    assert "b" in agg.failed_cases
