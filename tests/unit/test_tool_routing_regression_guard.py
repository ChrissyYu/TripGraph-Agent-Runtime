"""Unit tests for tool routing regression guard (Phase 9D)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from eval.tool_eval.baseline import (
    BaselineNotFoundError,
    load_tool_routing_baseline,
    save_tool_routing_baseline,
)
from eval.tool_eval.models import (
    MultiToolMetrics,
    ToolRoutingBaseline,
    ToolRoutingEvalReport,
    ToolRoutingRegressionThresholds,
)
from eval.tool_eval.regression_guard import ToolRoutingRegressionGuard


def _baseline(**overrides) -> ToolRoutingBaseline:
    data = {
        "dataset_path": "eval/datasets/tool_routing.jsonl",
        "dataset_hash": "abc123",
        "policy_strategy": "mixed",
        "total_cases": 12,
        "tool_selection_accuracy": 0.9091,
        "family_accuracy": 1.0,
        "provider_accuracy": 0.9167,
        "mcp_usage_rate": 0.3333,
        "builtin_usage_rate": 0.5833,
        "fallback_rate": 0.0833,
        "fallback_success_rate": 1.0,
        "average_confidence": 0.8,
        "created_at": datetime.now(UTC),
    }
    data.update(overrides)
    return ToolRoutingBaseline.model_validate(data)


def _report(**overrides) -> ToolRoutingEvalReport:
    data = {
        "total_cases": 12,
        "tool_selection_accuracy": 0.9091,
        "family_accuracy": 1.0,
        "provider_accuracy": 0.9167,
        "mcp_usage_rate": 0.3333,
        "builtin_usage_rate": 0.5833,
        "fallback_rate": 0.0833,
        "fallback_success_rate": 1.0,
        "average_confidence": 0.8,
        "dataset_hash": "abc123",
    }
    data.update(overrides)
    return ToolRoutingEvalReport.model_validate(data)


def test_save_and_load_baseline(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    report = _report()
    save_tool_routing_baseline(
        report,
        dataset_path="eval/datasets/tool_routing.jsonl",
        dataset_hash="abc123",
        policy_strategy="mixed",
        baseline_path=path,
    )
    loaded = load_tool_routing_baseline(path)
    assert loaded.baseline_schema_version == "v1"
    assert loaded.tool_selection_accuracy == pytest.approx(0.9091)
    assert loaded.dataset_hash == "abc123"


def test_no_regression_when_metrics_same() -> None:
    guard = ToolRoutingRegressionGuard()
    result = guard.compare(_report(), _baseline())
    assert result.regression_detected is False
    assert result.degraded is False


def test_detects_accuracy_drop() -> None:
    guard = ToolRoutingRegressionGuard()
    current = _report(tool_selection_accuracy=0.80)
    result = guard.compare(current, _baseline())
    assert result.regression_detected is True
    assert "tool_selection_accuracy_drop" in result.failed_thresholds


def test_detects_provider_accuracy_drop() -> None:
    guard = ToolRoutingRegressionGuard()
    current = _report(provider_accuracy=0.80)
    result = guard.compare(current, _baseline())
    assert result.regression_detected is True
    assert "provider_accuracy_drop" in result.failed_thresholds


def test_detects_fallback_rate_increase() -> None:
    guard = ToolRoutingRegressionGuard()
    current = _report(fallback_rate=0.25)
    result = guard.compare(current, _baseline())
    assert result.degraded is True
    assert "fallback_rate_increase" in result.failed_thresholds
    assert result.regression_detected is False


def test_missing_baseline_returns_friendly_error(tmp_path: Path) -> None:
    guard = ToolRoutingRegressionGuard()
    missing = tmp_path / "missing.json"
    result = guard.compare(_report(), baseline_path=str(missing))
    assert result.regression_detected is False
    assert result.baseline_available is False
    assert "baseline_missing" in result.warnings

    with pytest.raises(BaselineNotFoundError):
        load_tool_routing_baseline(missing)
