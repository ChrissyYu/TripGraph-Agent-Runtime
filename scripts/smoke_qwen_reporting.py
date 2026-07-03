"""Shared reporting helpers for Qwen smoke script and unit tests."""

from __future__ import annotations

from core.llm.fallback_trace import (
    LLMFallbackEvent,
    get_fallback_events,
    planner_fallback_summary,
    timeout_suggestion,
)
from plan.final_synthesis import check_final_result_coverage


def build_planner_fallback_lines(
    *,
    events: list[LLMFallbackEvent] | None = None,
    timeout_sec: float,
) -> list[str]:
    summary = planner_fallback_summary(events)
    lines = [f"planner_fallback_used: {summary['planner_fallback_used']}"]
    if summary["planner_fallback_used"]:
        error_type = summary["planner_error_type"]
        if error_type:
            lines.append(f"planner_error_type={error_type}")
        reason = summary["planner_fallback_reason"]
        if reason:
            lines.append(f"planner_fallback_reason: {reason}")
        suggestion = timeout_suggestion(error_type, timeout_sec)
        if suggestion:
            lines.append(f"Suggestion: {suggestion}")
    return lines


def build_coverage_lines(final_result: str) -> list[str]:
    coverage = check_final_result_coverage(final_result)
    lines = ["Final result coverage:"]
    for key in (
        "contains_weather_section",
        "contains_route_section",
        "contains_budget_section",
    ):
        lines.append(f"  {key}: {coverage[key]}")
    return lines


def collect_smoke_diagnostics(
    final_result: str,
    *,
    timeout_sec: float,
    events: list[LLMFallbackEvent] | None = None,
) -> dict[str, object]:
    resolved_events = events if events is not None else get_fallback_events()
    summary = planner_fallback_summary(resolved_events)
    coverage = check_final_result_coverage(final_result)
    return {
        **summary,
        **coverage,
        "timeout_suggestion": timeout_suggestion(summary["planner_error_type"], timeout_sec),
    }
