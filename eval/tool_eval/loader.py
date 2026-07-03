"""Load tool routing evaluation datasets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eval.tool_eval.models import ToolRoutingCase

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "datasets" / "tool_routing.jsonl"
DEFAULT_MULTI_DATASET = Path(__file__).resolve().parents[1] / "datasets" / "tool_routing_multi.jsonl"


def compute_dataset_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: str(p)):
        digest.update(str(path).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _load_cases_from_file(dataset_path: Path) -> list[ToolRoutingCase]:
    if not dataset_path.exists():
        return []
    cases: list[ToolRoutingCase] = []
    with dataset_path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                payload = json.loads(stripped)
                cases.append(ToolRoutingCase.model_validate(payload))
            except Exception as exc:
                raise ValueError(f"Invalid case at {dataset_path}:{line_no}: {exc}") from exc
    return cases


def load_tool_routing_dataset(
    path: Path | str | None = None,
    *,
    include_multi: bool = True,
    multi_path: Path | str | None = None,
) -> tuple[list[ToolRoutingCase], str, list[str]]:
    """Load single + optional multi-tool cases; return cases, dataset_hash, source paths."""
    primary = Path(path) if path else DEFAULT_DATASET
    if not primary.exists():
        raise FileNotFoundError(f"Tool routing dataset not found: {primary}")

    source_paths = [primary]
    cases = _load_cases_from_file(primary)

    if include_multi:
        multi = Path(multi_path) if multi_path else DEFAULT_MULTI_DATASET
        if multi.exists():
            source_paths.append(multi)
            cases.extend(_load_cases_from_file(multi))

    dataset_hash = compute_dataset_hash(source_paths)
    return cases, dataset_hash, [str(p) for p in source_paths]
