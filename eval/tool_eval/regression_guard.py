"""Tool routing regression detection (Phase 9D)."""

from __future__ import annotations

from eval.tool_eval.baseline import BaselineNotFoundError, load_tool_routing_baseline
from eval.tool_eval.models import (
    ToolRoutingBaseline,
    ToolRoutingEvalReport,
    ToolRoutingRegressionReport,
    ToolRoutingRegressionThresholds,
)


class ToolRoutingRegressionGuard:
    """Compare current tool routing eval report against a saved baseline."""

    def __init__(
        self,
        thresholds: ToolRoutingRegressionThresholds | None = None,
    ) -> None:
        self._thresholds = thresholds or ToolRoutingRegressionThresholds()

    @property
    def thresholds(self) -> ToolRoutingRegressionThresholds:
        return self._thresholds

    def compare(
        self,
        current: ToolRoutingEvalReport,
        baseline: ToolRoutingBaseline | None = None,
        *,
        baseline_path: str | None = None,
    ) -> ToolRoutingRegressionReport:
        if baseline is None:
            try:
                baseline = load_tool_routing_baseline(baseline_path)
            except BaselineNotFoundError as exc:
                return ToolRoutingRegressionReport(
                    regression_detected=False,
                    degraded=False,
                    baseline_available=False,
                    summary=str(exc),
                    warnings=["baseline_missing"],
                )

        metric_deltas = {
            "tool_selection_accuracy": round(
                current.tool_selection_accuracy - baseline.tool_selection_accuracy,
                4,
            ),
            "family_accuracy": round(
                current.family_accuracy - baseline.family_accuracy,
                4,
            ),
            "provider_accuracy": round(
                current.provider_accuracy - baseline.provider_accuracy,
                4,
            ),
            "fallback_rate": round(current.fallback_rate - baseline.fallback_rate, 4),
            "mcp_usage_rate": round(current.mcp_usage_rate - baseline.mcp_usage_rate, 4),
            "average_confidence": round(
                current.average_confidence - baseline.average_confidence,
                4,
            ),
        }

        failed_thresholds: list[str] = []
        warnings: list[str] = []

        if metric_deltas["tool_selection_accuracy"] < -self._thresholds.tool_selection_accuracy_drop_tolerance:
            failed_thresholds.append("tool_selection_accuracy_drop")
        if metric_deltas["provider_accuracy"] < -self._thresholds.provider_accuracy_drop_tolerance:
            failed_thresholds.append("provider_accuracy_drop")
        if metric_deltas["family_accuracy"] < -self._thresholds.family_accuracy_drop_tolerance:
            failed_thresholds.append("family_accuracy_drop")
        if metric_deltas["fallback_rate"] > self._thresholds.fallback_rate_increase_tolerance:
            failed_thresholds.append("fallback_rate_increase")

        regression_detected = any(
            name.endswith("_drop") for name in failed_thresholds
        )
        degraded = regression_detected or "fallback_rate_increase" in failed_thresholds

        if baseline.dataset_hash and current.dataset_hash and baseline.dataset_hash != current.dataset_hash:
            warnings.append("dataset_hash_mismatch")

        summary_parts: list[str] = []
        if regression_detected:
            summary_parts.append(
                f"Regression detected: {', '.join(failed_thresholds)}.",
            )
        elif degraded:
            summary_parts.append(
                f"Degraded (non-blocking accuracy): fallback_rate delta={metric_deltas['fallback_rate']:+.4f}.",
            )
        else:
            summary_parts.append("No regression detected.")

        return ToolRoutingRegressionReport(
            regression_detected=regression_detected,
            degraded=degraded,
            baseline_available=True,
            baseline_path=baseline_path,
            metric_deltas=metric_deltas,
            failed_thresholds=failed_thresholds,
            warnings=warnings,
            summary=" ".join(summary_parts),
            baseline=baseline,
            current_summary=current.model_dump_summary(),
        )
