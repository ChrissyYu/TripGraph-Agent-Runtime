"""JSONL dataset loader."""

from __future__ import annotations

import json
from pathlib import Path

from eval.models import EvalCase

DATASETS_DIR = Path(__file__).resolve().parent / "datasets"
KNOWN_DATASETS = (
    "travel_eval",
    "budget_eval",
    "route_eval",
    "real_llm/qwen_smoke",
)


def resolve_dataset_path(name_or_path: str) -> Path:
    candidate = Path(name_or_path)
    if candidate.exists():
        return candidate

    normalized = name_or_path
    if not normalized.endswith(".jsonl"):
        normalized = f"{normalized}.jsonl"

    search_paths = [
        DATASETS_DIR / normalized,
        DATASETS_DIR / "real_llm" / Path(normalized).name,
    ]
    for bundled in search_paths:
        if bundled.exists():
            return bundled

    raise FileNotFoundError(f"Dataset not found: {name_or_path}")


def load_dataset(name_or_path: str) -> list[EvalCase]:
    path = resolve_dataset_path(name_or_path)
    cases: list[EvalCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        cases.append(EvalCase.model_validate(json.loads(line)))
    return cases


def list_datasets() -> list[str]:
    paths: list[Path] = list(DATASETS_DIR.glob("*.jsonl"))
    paths.extend(DATASETS_DIR.glob("real_llm/*.jsonl"))
    return sorted(
        str(path.relative_to(DATASETS_DIR)).removesuffix(".jsonl").replace("\\", "/")
        for path in paths
    )
