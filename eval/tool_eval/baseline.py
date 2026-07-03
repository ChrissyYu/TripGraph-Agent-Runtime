"""Tool routing eval baseline save/load (Phase 9D)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from eval.tool_eval.models import ToolRoutingBaseline, ToolRoutingEvalReport

DEFAULT_BASELINE_PATH = Path(__file__).resolve().parents[1] / "baselines" / "tool_routing_baseline.json"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _normalize_dataset_path(dataset_path: str) -> str:
    """Store repo-relative paths in versioned baselines."""
    parts = [part.strip() for part in dataset_path.split(",") if part.strip()]
    normalized: list[str] = []
    for part in parts:
        path = Path(part)
        try:
            normalized.append(str(path.relative_to(REPO_ROOT)))
        except ValueError:
            normalized.append(part.replace("\\", "/"))
    return ",".join(normalized)


class BaselineNotFoundError(FileNotFoundError):
    """Raised when baseline file is missing."""


def save_tool_routing_baseline(
    report: ToolRoutingEvalReport,
    *,
    dataset_path: str,
    dataset_hash: str,
    policy_strategy: str,
    baseline_path: Path | str | None = None,
) -> Path:
    path = Path(baseline_path) if baseline_path else DEFAULT_BASELINE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    baseline = ToolRoutingBaseline(
        baseline_schema_version="v1",
        dataset_path=_normalize_dataset_path(dataset_path),
        dataset_hash=dataset_hash,
        policy_strategy=policy_strategy,
        total_cases=report.total_cases,
        tool_selection_accuracy=report.tool_selection_accuracy,
        family_accuracy=report.family_accuracy,
        provider_accuracy=report.provider_accuracy,
        mcp_usage_rate=report.mcp_usage_rate,
        builtin_usage_rate=report.builtin_usage_rate,
        fallback_rate=report.fallback_rate,
        fallback_success_rate=report.fallback_success_rate,
        average_confidence=report.average_confidence,
        multi_tool_metrics=report.multi_tool_metrics,
        created_at=datetime.now(UTC),
    )
    payload = baseline.model_dump(mode="json")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_tool_routing_baseline(path: Path | str | None = None) -> ToolRoutingBaseline:
    file_path = Path(path) if path else DEFAULT_BASELINE_PATH
    if not file_path.exists():
        raise BaselineNotFoundError(
            f"Tool routing baseline not found: {file_path}. "
            "Run `python scripts/eval_tool_routing.py --save-baseline` first.",
        )
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    return ToolRoutingBaseline.model_validate(raw)
