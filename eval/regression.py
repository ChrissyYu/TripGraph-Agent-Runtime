"""Regression detection against stored baseline."""

from __future__ import annotations

from eval.models import EvalRunReport, RegressionReport
from eval.store import EvalStore


class RegressionGuard:
    def __init__(self, store: EvalStore, *, threshold: float = -0.05) -> None:
        self._store = store
        self._threshold = threshold

    @property
    def threshold(self) -> float:
        return self._threshold

    def save_baseline(self, report: EvalRunReport) -> None:
        self._store.save_baseline(report)

    def compare(
        self,
        current: EvalRunReport | None = None,
        *,
        baseline: dict | None = None,
    ) -> RegressionReport:
        baseline_data = baseline if baseline is not None else self._store.get_baseline()
        current_report = current or self._store.get_latest_run()

        if baseline_data is None or current_report is None:
            return RegressionReport(
                regression_detected=False,
                summary="Baseline or current run unavailable; regression check skipped.",
                baseline_run_id=baseline_data.get("run_id") if baseline_data else None,
                current_run_id=current_report.run_id if current_report else None,
            )

        baseline_score = float(baseline_data.get("aggregate_score", 0.0))
        current_score = current_report.aggregate_score
        delta = round(current_score - baseline_score, 4)
        regression_detected = delta < self._threshold

        baseline_cases = {
            item["case_id"]: item for item in baseline_data.get("cases", [])
        }
        per_case_diff: list[dict] = []
        for case in current_report.cases:
            base = baseline_cases.get(case.case_id)
            if base is None:
                per_case_diff.append(
                    {
                        "case_id": case.case_id,
                        "baseline_score": None,
                        "current_score": case.scores.total_score,
                        "delta": None,
                        "regressed": False,
                    },
                )
                continue
            case_delta = round(case.scores.total_score - float(base.get("total_score", 0.0)), 4)
            per_case_diff.append(
                {
                    "case_id": case.case_id,
                    "baseline_score": base.get("total_score"),
                    "current_score": case.scores.total_score,
                    "delta": case_delta,
                    "regressed": case_delta < self._threshold,
                },
            )

        summary = (
            f"Regression detected: score dropped {abs(delta):.4f} "
            f"(baseline={baseline_score:.4f}, current={current_score:.4f})."
            if regression_detected
            else f"No regression: delta={delta:+.4f} (threshold={self._threshold:+.4f})."
        )

        return RegressionReport(
            regression_detected=regression_detected,
            delta_score=delta,
            baseline_run_id=baseline_data.get("run_id"),
            current_run_id=current_report.run_id,
            baseline_score=baseline_score,
            current_score=current_score,
            threshold=self._threshold,
            per_case_diff=per_case_diff,
            summary=summary,
        )
