"""Tool routing evaluation models (Phase 9C/9D)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from tools.policy.models import ToolPolicyStrategy


class ToolRoutingCase(BaseModel):
    id: str
    query: str
    task: str = ""
    tasks: list[str] | None = None
    expected_tool_family: str = "unknown"
    expected_tool_families: list[str] | None = None
    expected_provider: Literal["builtin", "mcp", "unknown"] = "unknown"
    expected_tool: str | None = None
    expected_tools: list[str] | None = None
    policy_strategy: ToolPolicyStrategy | str = ToolPolicyStrategy.PLANNER_HINT_FIRST
    tool_hint: str | None = None
    tool_hints: list[str | None] | None = None
    difficulty: str = "easy"
    simulate_mcp_failure: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_single_or_multi(self) -> ToolRoutingCase:
        if self.is_multi_tool:
            if not self.tasks:
                raise ValueError("multi-tool case requires non-empty tasks")
            if not self.expected_tools:
                raise ValueError("multi-tool case requires expected_tools")
        elif not self.task:
            raise ValueError("single-tool case requires task")
        return self

    @property
    def is_multi_tool(self) -> bool:
        return self.tasks is not None and len(self.tasks) > 0


class ToolRoutingCaseResult(BaseModel):
    case_id: str
    selected_tool: str | None = None
    selected_tools: list[str] = Field(default_factory=list)
    selected_provider: str = "unknown"
    tool_family: str = "unknown"
    tool_selection_match: bool = False
    family_match: bool = False
    provider_match: bool = False
    fallback_used: bool = False
    fallback_success: bool | None = None
    confidence: float = 0.0
    reason: str = ""
    policy_name: str = ""
    is_multi_tool: bool = False
    tool_recall: float | None = None
    tool_precision: float | None = None
    family_recall: float | None = None
    provider_recall: float | None = None


class MultiToolMetrics(BaseModel):
    case_count: int = 0
    average_tool_recall: float = 0.0
    average_tool_precision: float = 0.0
    average_family_recall: float = 0.0
    average_provider_recall: float = 0.0


class ToolRoutingRegressionThresholds(BaseModel):
    tool_selection_accuracy_drop_tolerance: float = 0.05
    provider_accuracy_drop_tolerance: float = 0.05
    family_accuracy_drop_tolerance: float = 0.02
    fallback_rate_increase_tolerance: float = 0.10


class ToolRoutingBaseline(BaseModel):
    baseline_schema_version: str = "v1"
    dataset_path: str
    dataset_hash: str
    policy_strategy: str
    total_cases: int
    tool_selection_accuracy: float
    family_accuracy: float
    provider_accuracy: float
    mcp_usage_rate: float
    builtin_usage_rate: float
    fallback_rate: float
    fallback_success_rate: float
    average_confidence: float
    multi_tool_metrics: MultiToolMetrics | None = None
    created_at: datetime


class ToolRoutingRegressionReport(BaseModel):
    regression_detected: bool = False
    degraded: bool = False
    baseline_available: bool = True
    baseline_path: str | None = None
    metric_deltas: dict[str, float] = Field(default_factory=dict)
    failed_thresholds: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: str = ""
    baseline: ToolRoutingBaseline | None = None
    current_summary: dict[str, Any] = Field(default_factory=dict)


class ToolRoutingEvalReport(BaseModel):
    total_cases: int = 0
    tool_selection_accuracy: float = 0.0
    family_accuracy: float = 0.0
    provider_accuracy: float = 0.0
    mcp_usage_rate: float = 0.0
    builtin_usage_rate: float = 0.0
    fallback_rate: float = 0.0
    fallback_success_rate: float = 0.0
    average_confidence: float = 0.0
    per_case_results: list[ToolRoutingCaseResult] = Field(default_factory=list)
    policy_counters: dict[str, int] = Field(default_factory=dict)
    dataset_hash: str = ""
    dataset_path: str = ""
    policy_strategy: str = "mixed"
    baseline_path: str | None = None
    regression_summary: ToolRoutingRegressionReport | None = None
    thresholds: ToolRoutingRegressionThresholds = Field(
        default_factory=ToolRoutingRegressionThresholds,
    )
    multi_tool_metrics: MultiToolMetrics | None = None
    best_cases: list[str] = Field(default_factory=list)
    worst_cases: list[str] = Field(default_factory=list)

    def model_dump_summary(self) -> dict[str, Any]:
        summary = {
            "total_cases": self.total_cases,
            "tool_selection_accuracy": round(self.tool_selection_accuracy, 4),
            "family_accuracy": round(self.family_accuracy, 4),
            "provider_accuracy": round(self.provider_accuracy, 4),
            "mcp_usage_rate": round(self.mcp_usage_rate, 4),
            "builtin_usage_rate": round(self.builtin_usage_rate, 4),
            "fallback_rate": round(self.fallback_rate, 4),
            "fallback_success_rate": round(self.fallback_success_rate, 4),
            "average_confidence": round(self.average_confidence, 4),
            "dataset_hash": self.dataset_hash,
            "policy_strategy": self.policy_strategy,
        }
        if self.multi_tool_metrics and self.multi_tool_metrics.case_count:
            summary["multi_tool_metrics"] = self.multi_tool_metrics.model_dump()
        return summary
