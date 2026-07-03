"""Evaluation API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EvalRunRequest(BaseModel):
    dataset: str = Field(..., min_length=1, description="Dataset name or jsonl path")
    seed: int = 42
    run_id: str | None = None
    case_ids: list[str] | None = None
    save_baseline: bool = False


class EvalReportQuery(BaseModel):
    run_id: str | None = None
