"""Graph-level demo evaluation models (Phase 10A)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class GraphDemoEvalCase(BaseModel):
    id: str
    query: str
    expected_tool_families: list[str] = Field(default_factory=list)
    expected_tools: list[str] | None = None
    expected_providers: list[str] | None = None
    expected_final_sections: list[str] = Field(default_factory=list)
    policy_strategy: str | None = None
    mcp_enabled: bool = False
    allow_replan: bool = True
    difficulty: str = "medium"
    notes: str | None = None


class GraphDemoEvalResult(BaseModel):
    id: str
    query: str
    execution_success: bool = False
    plan_validity: bool = False
    final_result_present: bool = False
    expected_tool_families: list[str] = Field(default_factory=list)
    actual_tool_families: list[str] = Field(default_factory=list)
    expected_tools: list[str] | None = None
    actual_tools: list[str] = Field(default_factory=list)
    expected_providers: list[str] | None = None
    actual_providers: list[str] = Field(default_factory=list)
    tool_family_recall: float | None = None
    tool_family_precision: float | None = None
    tool_selection_recall: float | None = None
    tool_selection_precision: float | None = None
    provider_recall: float | None = None
    provider_precision: float | None = None
    expected_final_sections: list[str] = Field(default_factory=list)
    actual_final_sections: list[str] = Field(default_factory=list)
    final_section_coverage: float | None = None
    fallback_used: bool = False
    replan_used: bool = False
    replan_count: int = 0
    latency_ms: float = 0.0
    error_type: str | None = None
    error_message: str | None = None
    execution_id: str | None = None
    tool_extraction_source: str | None = None


class GraphDemoLowRecallCase(BaseModel):
    id: str
    query: str
    expected_tools: list[str] | None = None
    actual_tools: list[str] = Field(default_factory=list)
    expected_providers: list[str] | None = None
    actual_providers: list[str] = Field(default_factory=list)
    tool_selection_recall: float | None = None
    provider_recall: float | None = None
    tool_selection_precision: float | None = None
    provider_precision: float | None = None
    mismatch_reason: str = ""


class GraphDemoAggregateMetrics(BaseModel):
    total_cases: int = 0
    execution_success_rate: float = 0.0
    avg_tool_family_recall: float | None = None
    avg_tool_family_precision: float | None = None
    avg_tool_selection_recall: float | None = None
    avg_tool_selection_precision: float | None = None
    avg_provider_recall: float | None = None
    avg_provider_precision: float | None = None
    avg_final_section_coverage: float | None = None
    fallback_rate: float = 0.0
    replan_rate: float = 0.0
    avg_latency_ms: float = 0.0
    failed_cases: list[str] = Field(default_factory=list)


class GraphDemoEvalReport(BaseModel):
    created_at: datetime
    dataset_path: str
    dataset_hash: str
    eval_mode: str = "deterministic_eval"
    llm_provider: str = "rule_based"
    total_cases: int = 0
    aggregate_metrics: GraphDemoAggregateMetrics = Field(default_factory=GraphDemoAggregateMetrics)
    per_case_results: list[GraphDemoEvalResult] = Field(default_factory=list)
    failed_cases: list[str] = Field(default_factory=list)
    low_tool_selection_recall_cases: list[GraphDemoLowRecallCase] = Field(default_factory=list)
    low_provider_recall_cases: list[GraphDemoLowRecallCase] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def model_dump_summary(self) -> dict[str, Any]:
        agg = self.aggregate_metrics
        summary: dict[str, Any] = {
            "total_cases": self.total_cases,
            "execution_success_rate": round(agg.execution_success_rate, 4),
            "fallback_rate": round(agg.fallback_rate, 4),
            "replan_rate": round(agg.replan_rate, 4),
            "avg_latency_ms": round(agg.avg_latency_ms, 2),
            "dataset_hash": self.dataset_hash,
            "eval_mode": self.eval_mode,
            "llm_provider": self.llm_provider,
        }
        if agg.avg_tool_family_recall is not None:
            summary["avg_tool_family_recall"] = round(agg.avg_tool_family_recall, 4)
        if agg.avg_tool_family_precision is not None:
            summary["avg_tool_family_precision"] = round(agg.avg_tool_family_precision, 4)
        if agg.avg_tool_selection_recall is not None:
            summary["avg_tool_selection_recall"] = round(agg.avg_tool_selection_recall, 4)
        if agg.avg_tool_selection_precision is not None:
            summary["avg_tool_selection_precision"] = round(agg.avg_tool_selection_precision, 4)
        if agg.avg_provider_recall is not None:
            summary["avg_provider_recall"] = round(agg.avg_provider_recall, 4)
        if agg.avg_provider_precision is not None:
            summary["avg_provider_precision"] = round(agg.avg_provider_precision, 4)
        if agg.avg_final_section_coverage is not None:
            summary["avg_final_section_coverage"] = round(agg.avg_final_section_coverage, 4)
        if self.low_tool_selection_recall_cases:
            summary["low_tool_selection_recall_cases"] = [
                case.model_dump() for case in self.low_tool_selection_recall_cases
            ]
        if self.low_provider_recall_cases:
            summary["low_provider_recall_cases"] = [
                case.model_dump() for case in self.low_provider_recall_cases
            ]
        if agg.failed_cases:
            summary["failed_cases"] = agg.failed_cases
        return summary
