"""Evaluation and regression service facade."""

from __future__ import annotations

from typing import Any

from eval.bootstrap import EvalBundle
from eval.loader import list_datasets
from eval.models import EvalRunReport
from schemas.eval import EvalRunRequest


class EvalService:
    def __init__(self, bundle: EvalBundle) -> None:
        self._bundle = bundle

    @property
    def enabled(self) -> bool:
        return self._bundle.enabled and self._bundle.runner is not None

    async def run(self, body: EvalRunRequest) -> EvalRunReport:
        self._require_enabled()
        report = await self._bundle.runner.run_dataset(  # type: ignore[union-attr]
            body.dataset,
            seed=body.seed,
            run_id=body.run_id,
            case_ids=body.case_ids,
        )
        if body.save_baseline and self._bundle.regression is not None:
            self._bundle.regression.save_baseline(report)
        return report

    def get_report(self, run_id: str | None = None) -> EvalRunReport:
        self._require_enabled()
        report = self._bundle.runner.get_report(run_id)  # type: ignore[union-attr]
        if report is None:
            raise KeyError("Evaluation report not found")
        return report

    def regression(self, run_id: str | None = None) -> dict[str, Any]:
        self._require_enabled()
        if self._bundle.regression is None or self._bundle.store is None:
            raise RuntimeError("Regression guard unavailable")
        current = (
            self._bundle.runner.get_report(run_id)  # type: ignore[union-attr]
            if run_id and self._bundle.runner
            else self._bundle.store.get_latest_run()
        )
        regression = self._bundle.regression.compare(current=current)
        return {
            **regression.model_dump(mode="json"),
            "available_datasets": list_datasets(),
        }

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise RuntimeError("Evaluation system is disabled")
