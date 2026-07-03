"""Integration tests for graph demo eval runner."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from eval.graph_eval.evaluator import GraphDemoEvaluator, apply_deterministic_eval_env
from eval.graph_eval.loader import load_graph_demo_dataset
from eval.graph_eval.report import write_graph_demo_report

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def graph_evaluator() -> GraphDemoEvaluator:
    apply_deterministic_eval_env()
    from config.settings import get_settings

    get_settings.cache_clear()
    return GraphDemoEvaluator(eval_mode="deterministic_eval", llm_provider="rule_based")


@pytest.mark.asyncio
async def test_graph_demo_eval_runs_deterministic_builtin_case(graph_evaluator: GraphDemoEvaluator) -> None:
    cases, dataset_hash, dataset_path = load_graph_demo_dataset()
    case = next(case for case in cases if case.id == "graph-demo-builtin-trip-001")
    result = await graph_evaluator.run_case(case)
    assert result.execution_success
    assert result.plan_validity
    assert result.final_result_present
    assert result.tool_family_recall == 1.0
    assert result.provider_recall == 1.0
    assert result.final_section_coverage == 1.0
    assert "weather" in result.actual_tools
    assert result.error_type is None


@pytest.mark.asyncio
async def test_graph_demo_eval_runs_mcp_case_with_mock_server(
    graph_evaluator: GraphDemoEvaluator,
) -> None:
    cases, _, _ = load_graph_demo_dataset()
    case = next(case for case in cases if case.id == "graph-demo-mcp-trip-001")
    result = await graph_evaluator.run_case(case)
    assert result.execution_success
    assert all(tool.startswith("mcp_") for tool in result.actual_tools)
    assert result.provider_recall == 1.0
    assert result.tool_family_recall == 1.0


@pytest.mark.asyncio
async def test_graph_demo_eval_report_written(
    graph_evaluator: GraphDemoEvaluator,
    tmp_path: Path,
) -> None:
    cases, dataset_hash, dataset_path = load_graph_demo_dataset()
    report = await graph_evaluator.evaluate_cases(
        cases[:2],
        dataset_hash=dataset_hash,
        dataset_path=dataset_path,
    )
    output_path = write_graph_demo_report(report, output_dir=tmp_path)
    latest = tmp_path / "latest_report.json"
    assert output_path.exists()
    assert latest.exists()
    assert report.total_cases == 2
    assert report.aggregate_metrics.total_cases == 2


@pytest.mark.asyncio
async def test_graph_demo_eval_does_not_require_qwen_key(
    graph_evaluator: GraphDemoEvaluator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    os.environ.pop("QWEN_API_KEY", None)
    cases, _, _ = load_graph_demo_dataset()
    case = next(case for case in cases if case.id == "graph-demo-builtin-weather-001")
    result = await graph_evaluator.run_case(case)
    assert result.execution_success
    assert result.error_type is None
