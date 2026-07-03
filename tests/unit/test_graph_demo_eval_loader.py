"""Unit tests for graph demo eval dataset loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.graph_eval.loader import DEFAULT_DATASET, load_graph_demo_dataset
from eval.graph_eval.models import GraphDemoEvalCase

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_graph_demo_dataset_loads() -> None:
    cases, dataset_hash, dataset_path = load_graph_demo_dataset()
    assert len(cases) >= 12
    assert dataset_hash
    assert dataset_path.endswith("graph_demo_eval.jsonl")


def test_graph_demo_case_required_fields() -> None:
    cases, _, _ = load_graph_demo_dataset()
    for case in cases:
        assert isinstance(case, GraphDemoEvalCase)
        assert case.id
        assert case.query
        assert case.difficulty in {"easy", "medium", "hard"}


def test_graph_demo_dataset_has_builtin_and_mcp_cases() -> None:
    cases, _, _ = load_graph_demo_dataset()
    builtin_cases = [case for case in cases if not case.mcp_enabled]
    mcp_cases = [case for case in cases if case.mcp_enabled]
    assert len(builtin_cases) >= 4
    assert len(mcp_cases) >= 4
    assert DEFAULT_DATASET.exists()


def test_graph_demo_dataset_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.jsonl"
    with pytest.raises(FileNotFoundError):
        load_graph_demo_dataset(missing)
