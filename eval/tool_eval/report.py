"""Report helpers for tool routing evaluation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval.tool_eval.models import ToolRoutingEvalReport, ToolRoutingRegressionReport

DEFAULT_OUTPUT_DIR = Path("data/eval/tool_routing")
LATEST_REPORT_NAME = "latest_report.json"


def write_tool_routing_report(
    report: ToolRoutingEvalReport,
    *,
    output_dir: Path | str | None = None,
    regression_summary: ToolRoutingRegressionReport | None = None,
) -> Path:
    directory = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"tool_routing_report_{timestamp}.json"

    if regression_summary is not None:
        report = report.model_copy(update={"regression_summary": regression_summary})

    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": report.model_dump_summary(),
        "report": report.model_dump(mode="json"),
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(content, encoding="utf-8")

    latest_path = directory / LATEST_REPORT_NAME
    latest_path.write_text(content, encoding="utf-8")
    return path
