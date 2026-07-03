"""Evaluation run and baseline persistence."""

from __future__ import annotations

import json
from pathlib import Path

from eval.models import EvalRunReport


class EvalStore:
    def __init__(self, root_path: str) -> None:
        self._root = Path(root_path)
        self._runs_dir = self._root / "runs"
        self._baseline_path = self._root / "baseline.json"
        self._latest_path = self._root / "latest_run_id.txt"
        self._runs_dir.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def save_run(self, report: EvalRunReport) -> None:
        path = self._runs_dir / f"{report.run_id}.json"
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        self._latest_path.write_text(report.run_id, encoding="utf-8")

    def get_run(self, run_id: str) -> EvalRunReport | None:
        path = self._runs_dir / f"{run_id}.json"
        if not path.exists():
            return None
        return EvalRunReport.model_validate_json(path.read_text(encoding="utf-8"))

    def get_latest_run_id(self) -> str | None:
        if not self._latest_path.exists():
            return None
        run_id = self._latest_path.read_text(encoding="utf-8").strip()
        return run_id or None

    def get_latest_run(self) -> EvalRunReport | None:
        run_id = self.get_latest_run_id()
        if run_id is None:
            return None
        return self.get_run(run_id)

    def save_baseline(self, report: EvalRunReport) -> None:
        payload = {
            "run_id": report.run_id,
            "aggregate_score": report.aggregate_score,
            "aggregate_scores": report.aggregate_scores.model_dump(),
            "cases": [
                {
                    "case_id": case.case_id,
                    "total_score": case.scores.total_score,
                    "scores": case.scores.model_dump(),
                }
                for case in report.cases
            ],
        }
        self._baseline_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_baseline(self) -> dict | None:
        if not self._baseline_path.exists():
            return None
        return json.loads(self._baseline_path.read_text(encoding="utf-8"))

    def list_run_ids(self) -> list[str]:
        return sorted(path.stem for path in self._runs_dir.glob("*.json"))
