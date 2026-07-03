"""Recall / precision diagnostics for graph demo eval."""

from __future__ import annotations

from eval.graph_eval.models import GraphDemoEvalCase, GraphDemoEvalResult, GraphDemoLowRecallCase


def _norm_list(items: list[str] | None) -> set[str]:
    return {item.lower() for item in (items or [])}


def infer_tool_selection_mismatch_reason(
    case: GraphDemoEvalCase,
    result: GraphDemoEvalResult,
) -> str:
    expected = _norm_list(case.expected_tools)
    actual = _norm_list(result.actual_tools)
    missing = expected - actual
    extra = actual - expected

    parts: list[str] = []
    if missing:
        parts.append(f"missing expected tools: {sorted(missing)}")
        if "mcp" in case.query.lower() and all(name.startswith("mcp_") for name in missing):
            if actual and all(not name.startswith("mcp_") for name in actual):
                parts.append(
                    "RuleBased _build_default_plan omits prefer_mcp; planner emitted builtin hints "
                    "and policy respected them (real planner/policy behavior, not extraction gap)",
                )
    if extra:
        parts.append(
            f"extra actual tools: {sorted(extra)} (affects precision, not recall when expected are covered)",
        )
    if not parts:
        return "tool_selection_recall below threshold with no missing expected tools"
    return "; ".join(parts)


def infer_provider_mismatch_reason(
    case: GraphDemoEvalCase,
    result: GraphDemoEvalResult,
) -> str:
    expected = set(case.expected_providers or [])
    actual_unique = set(result.actual_providers)
    missing = expected - actual_unique
    unexpected = actual_unique - expected

    parts: list[str] = []
    if missing:
        parts.append(f"expected provider(s) not observed: {sorted(missing)}")
        if "mcp" in (case.expected_providers or []) and actual_unique == {"builtin"}:
            parts.append(
                "planner selected builtin tool hints despite MCP in query "
                "(dataset expectation vs RuleBased default-plan path)",
            )
    if unexpected:
        parts.append(
            f"unexpected provider(s) in actual: {sorted(unexpected)} (affects precision, not recall)",
        )
    if not parts:
        return "provider_recall below threshold"
    return "; ".join(parts)


def build_low_recall_diagnostics(
    cases: list[GraphDemoEvalCase],
    results: list[GraphDemoEvalResult],
    *,
    recall_threshold: float = 1.0,
) -> tuple[list[GraphDemoLowRecallCase], list[GraphDemoLowRecallCase]]:
    case_by_id = {case.id: case for case in cases}
    low_tool: list[GraphDemoLowRecallCase] = []
    low_provider: list[GraphDemoLowRecallCase] = []

    for result in results:
        case = case_by_id.get(result.id)
        if case is None:
            continue

        if (
            result.tool_selection_recall is not None
            and result.tool_selection_recall < recall_threshold
        ):
            low_tool.append(
                GraphDemoLowRecallCase(
                    id=result.id,
                    query=result.query,
                    expected_tools=case.expected_tools,
                    actual_tools=result.actual_tools,
                    expected_providers=case.expected_providers,
                    actual_providers=result.actual_providers,
                    tool_selection_recall=result.tool_selection_recall,
                    provider_recall=result.provider_recall,
                    tool_selection_precision=result.tool_selection_precision,
                    provider_precision=result.provider_precision,
                    mismatch_reason=infer_tool_selection_mismatch_reason(case, result),
                ),
            )

        if result.provider_recall is not None and result.provider_recall < recall_threshold:
            low_provider.append(
                GraphDemoLowRecallCase(
                    id=result.id,
                    query=result.query,
                    expected_tools=case.expected_tools,
                    actual_tools=result.actual_tools,
                    expected_providers=case.expected_providers,
                    actual_providers=result.actual_providers,
                    tool_selection_recall=result.tool_selection_recall,
                    provider_recall=result.provider_recall,
                    tool_selection_precision=result.tool_selection_precision,
                    provider_precision=result.provider_precision,
                    mismatch_reason=infer_provider_mismatch_reason(case, result),
                ),
            )

    return low_tool, low_provider
