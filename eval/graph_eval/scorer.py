"""Scoring helpers for graph demo evaluation."""

from __future__ import annotations

from eval.graph_eval.models import GraphDemoAggregateMetrics, GraphDemoEvalCase, GraphDemoEvalResult

FINAL_SECTION_MARKERS: dict[str, tuple[str, ...]] = {
    "目标": ("目标：", "目标:"),
    "天气信息": ("天气信息：", "天气信息:", "天气："),
    "行程路线": ("行程路线：", "行程路线:"),
    "预算估算": ("预算估算：", "预算估算:", "预算："),
    "总结": ("总结：", "总结:"),
}


def _normalized_sets(expected: list[str], actual: list[str]) -> tuple[set[str], set[str]]:
    return {item.lower() for item in expected}, {item.lower() for item in actual}


def set_recall(expected: list[str], actual: list[str]) -> float | None:
    """Recall = |expected ∩ actual| / |expected| on normalized tool/family names."""
    if not expected:
        return None
    expected_set, actual_set = _normalized_sets(expected, actual)
    if not expected_set:
        return None
    return len(expected_set & actual_set) / len(expected_set)


def set_precision(expected: list[str], actual: list[str]) -> float | None:
    """Precision = |expected ∩ actual| / |actual|. Extra tools lower precision, not recall."""
    if not expected:
        return None
    if not actual:
        return 0.0
    expected_set, actual_set = _normalized_sets(expected, actual)
    return len(expected_set & actual_set) / len(actual_set)


def provider_recall(expected_providers: list[str] | None, actual_providers: list[str]) -> float | None:
    """Provider recall on unique provider labels: |expected ∩ actual| / |expected|."""
    if not expected_providers:
        return None
    return set_recall(list(set(expected_providers)), list(set(actual_providers)))


def provider_precision(expected_providers: list[str] | None, actual_providers: list[str]) -> float | None:
    """Provider precision on unique provider labels: |expected ∩ actual| / |actual|."""
    if not expected_providers:
        return None
    return set_precision(list(set(expected_providers)), list(set(actual_providers)))


def extract_final_sections(final_result: str) -> list[str]:
    if not final_result:
        return []
    found: list[str] = []
    for section, markers in FINAL_SECTION_MARKERS.items():
        if any(marker in final_result for marker in markers):
            found.append(section)
    return found


def final_section_coverage(expected_sections: list[str], final_result: str) -> float | None:
    if not expected_sections:
        return None
    actual = extract_final_sections(final_result)
    return set_recall(expected_sections, actual)


class GraphDemoScorer:
    """Compute per-case and aggregate metrics for graph demo eval."""

    def score_case(
        self,
        case: GraphDemoEvalCase,
        *,
        execution_success: bool,
        plan_validity: bool,
        final_result: str,
        actual_tools: list[str],
        actual_tool_families: list[str],
        actual_providers: list[str],
        fallback_used: bool,
        replan_count: int,
        latency_ms: float,
        execution_id: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        tool_extraction_source: str | None = None,
    ) -> GraphDemoEvalResult:
        actual_sections = extract_final_sections(final_result)
        return GraphDemoEvalResult(
            id=case.id,
            query=case.query,
            execution_success=execution_success,
            plan_validity=plan_validity,
            final_result_present=bool(final_result.strip()),
            expected_tool_families=list(case.expected_tool_families),
            actual_tool_families=actual_tool_families,
            expected_tools=case.expected_tools,
            actual_tools=actual_tools,
            expected_providers=case.expected_providers,
            actual_providers=actual_providers,
            tool_family_recall=set_recall(case.expected_tool_families, actual_tool_families),
            tool_family_precision=set_precision(case.expected_tool_families, actual_tool_families)
            if case.expected_tool_families
            else None,
            tool_selection_recall=set_recall(case.expected_tools or [], actual_tools)
            if case.expected_tools
            else None,
            tool_selection_precision=set_precision(case.expected_tools or [], actual_tools)
            if case.expected_tools
            else None,
            provider_recall=provider_recall(case.expected_providers, actual_providers),
            provider_precision=provider_precision(case.expected_providers, actual_providers),
            expected_final_sections=list(case.expected_final_sections),
            actual_final_sections=actual_sections,
            final_section_coverage=final_section_coverage(case.expected_final_sections, final_result),
            fallback_used=fallback_used,
            replan_used=replan_count > 0,
            replan_count=replan_count,
            latency_ms=latency_ms,
            error_type=error_type,
            error_message=error_message,
            execution_id=execution_id,
            tool_extraction_source=tool_extraction_source,
        )

    def aggregate(self, results: list[GraphDemoEvalResult]) -> GraphDemoAggregateMetrics:
        total = len(results)
        if total == 0:
            return GraphDemoAggregateMetrics()

        success_count = sum(1 for result in results if result.execution_success)
        fallback_count = sum(1 for result in results if result.fallback_used)
        replan_count = sum(1 for result in results if result.replan_used)

        failed_cases = [
            result.id
            for result in results
            if not result.execution_success or (result.error_type is not None)
        ]

        return GraphDemoAggregateMetrics(
            total_cases=total,
            execution_success_rate=success_count / total,
            avg_tool_family_recall=_average_optional(result.tool_family_recall for result in results),
            avg_tool_family_precision=_average_optional(
                result.tool_family_precision for result in results
            ),
            avg_tool_selection_recall=_average_optional(
                result.tool_selection_recall for result in results
            ),
            avg_tool_selection_precision=_average_optional(
                result.tool_selection_precision for result in results
            ),
            avg_provider_recall=_average_optional(result.provider_recall for result in results),
            avg_provider_precision=_average_optional(result.provider_precision for result in results),
            avg_final_section_coverage=_average_optional(
                result.final_section_coverage for result in results
            ),
            fallback_rate=fallback_count / total,
            replan_rate=replan_count / total,
            avg_latency_ms=sum(result.latency_ms for result in results) / total,
            failed_cases=failed_cases,
        )


def _average_optional(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present) / len(present)
