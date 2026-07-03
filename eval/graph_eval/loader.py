"""Load graph demo evaluation datasets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eval.graph_eval.models import GraphDemoEvalCase

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "datasets" / "graph_demo_eval.jsonl"


def compute_dataset_hash(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(str(path).encode("utf-8"))
    digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def load_graph_demo_dataset(path: Path | str | None = None) -> tuple[list[GraphDemoEvalCase], str, str]:
    """Load cases from JSONL; return cases, dataset_hash, dataset_path string."""
    dataset_path = Path(path) if path else DEFAULT_DATASET
    if not dataset_path.exists():
        raise FileNotFoundError(f"Graph demo dataset not found: {dataset_path}")

    cases: list[GraphDemoEvalCase] = []
    with dataset_path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                payload = json.loads(stripped)
                cases.append(GraphDemoEvalCase.model_validate(payload))
            except Exception as exc:
                raise ValueError(f"Invalid case at {dataset_path}:{line_no}: {exc}") from exc

    dataset_hash = compute_dataset_hash(dataset_path)
    return cases, dataset_hash, str(dataset_path)
