"""Report helpers for graph demo evaluation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval.graph_eval.models import GraphDemoEvalReport

DEFAULT_OUTPUT_DIR = Path("data/eval/graph_demo")
LATEST_REPORT_NAME = "latest_report.json"


def write_graph_demo_report(
    report: GraphDemoEvalReport,
    *,
    output_dir: Path | str | None = None,
) -> Path:
    directory = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"graph_demo_report_{timestamp}.json"

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
