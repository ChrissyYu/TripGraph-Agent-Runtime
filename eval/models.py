"""Evaluation domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class EvalCase(BaseModel):
    id: str
    query: str
    expected_tools: list[str] = Field(default_factory=list)
    expected_output_schema: dict[str, Any] = Field(default_factory=dict)
    difficulty: str = "medium"


class CaseScore(BaseModel):
    tool_accuracy: float = 0.0
    plan_quality: float = 0.0
    execution_success: float = 0.0
    cost_efficiency: float = 0.0
    total_score: float = 0.0


class EvalCaseResult(BaseModel):
    case_id: str
    query: str
    final_result: str = ""
    execution_trace: list[dict[str, Any]] = Field(default_factory=list)
    graph_trace: list[dict[str, Any]] = Field(default_factory=list)
    cost_metrics: dict[str, Any] = Field(default_factory=dict)
    latency_metrics: dict[str, Any] = Field(default_factory=dict)
    execution_id: str | None = None
    scores: CaseScore = Field(default_factory=CaseScore)
    error: str | None = None
    tools_used: list[str] = Field(default_factory=list)


class EvalRunReport(BaseModel):
    run_id: str
    dataset: str
    seed: int
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    case_count: int = 0
    passed_count: int = 0
    aggregate_score: float = 0.0
    aggregate_scores: CaseScore = Field(default_factory=CaseScore)
    cases: list[EvalCaseResult] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RegressionReport(BaseModel):
    regression_detected: bool = False
    delta_score: float = 0.0
    baseline_run_id: str | None = None
    current_run_id: str | None = None
    baseline_score: float = 0.0
    current_score: float = 0.0
    threshold: float = 0.0
    per_case_diff: list[dict[str, Any]] = Field(default_factory=list)
    summary: str = ""
