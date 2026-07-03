"""Tool routing policy evaluator (Phase 9C/9D)."""

from __future__ import annotations

from typing import Any

from eval.tool_eval.models import (
    MultiToolMetrics,
    ToolRoutingCase,
    ToolRoutingCaseResult,
    ToolRoutingEvalReport,
)
from tools.policy.models import ToolPolicyDecision
from tools.policy.engine import ToolPolicyEngine
from tools.policy.models import tool_family, tool_provider
from tools.policy.trace import ToolPolicyTracer
from tools.registry import ToolRegistry


class ToolRoutingEvaluator:
    """Evaluate ToolPolicyEngine decisions against labeled cases."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        mcp_enabled: bool = True,
        mcp_tool_prefix: str = "mcp_",
    ) -> None:
        self._registry = registry
        self._mcp_enabled = mcp_enabled
        self._mcp_prefix = mcp_tool_prefix

    def evaluate_cases(
        self,
        cases: list[ToolRoutingCase],
        *,
        dataset_hash: str = "",
        dataset_path: str = "",
    ) -> ToolRoutingEvalReport:
        tracer = ToolPolicyTracer(trace_enabled=False)
        per_case: list[ToolRoutingCaseResult] = []
        fallback_used_count = 0
        fallback_success_count = 0
        multi_results: list[ToolRoutingCaseResult] = []

        for case in cases:
            if case.is_multi_tool:
                result, _decision = self._evaluate_multi_tool_case(case)
                multi_results.append(result)
            else:
                result, decision = self._evaluate_single_tool_case(case)
                if result.fallback_used:
                    fallback_used_count += 1
                    if result.fallback_success:
                        fallback_success_count += 1
                tracer.record(
                    decision,
                    step_id=0,
                    task=case.task,
                    query=case.query,
                )
            per_case.append(result)

        single_cases = [r for r, c in zip(per_case, cases) if not c.is_multi_tool]
        total = len(cases) or 1
        single_total = len(single_cases) or 1

        labeled_indices = [
            i for i, c in enumerate(cases)
            if not c.is_multi_tool and c.expected_tool
        ]
        if labeled_indices:
            tool_acc = sum(
                1 for i in labeled_indices if per_case[i].tool_selection_match
            ) / len(labeled_indices)
        else:
            tool_acc = sum(1 for r in single_cases if r.tool_selection_match) / single_total

        multi_tool_metrics = self._aggregate_multi_tool_metrics(multi_results)

        strategies = {str(c.policy_strategy) for c in cases}
        policy_strategy = strategies.pop() if len(strategies) == 1 else "mixed"

        report = ToolRoutingEvalReport(
            total_cases=len(cases),
            tool_selection_accuracy=tool_acc,
            family_accuracy=sum(1 for r in single_cases if r.family_match) / single_total,
            provider_accuracy=sum(1 for r in single_cases if r.provider_match) / single_total,
            mcp_usage_rate=sum(1 for r in per_case if r.selected_provider == "mcp") / total,
            builtin_usage_rate=sum(1 for r in per_case if r.selected_provider == "builtin") / total,
            fallback_rate=fallback_used_count / total,
            fallback_success_rate=(
                fallback_success_count / fallback_used_count
                if fallback_used_count
                else 0.0
            ),
            average_confidence=sum(r.confidence for r in per_case) / total,
            per_case_results=per_case,
            policy_counters=tracer.counters,
            dataset_hash=dataset_hash,
            dataset_path=dataset_path,
            policy_strategy=policy_strategy,
            multi_tool_metrics=multi_tool_metrics,
            best_cases=self._rank_cases(per_case, best=True),
            worst_cases=self._rank_cases(per_case, best=False),
        )
        return report

    def _evaluate_single_tool_case(
        self,
        case: ToolRoutingCase,
    ) -> tuple[ToolRoutingCaseResult, ToolPolicyDecision]:
        engine = ToolPolicyEngine(
            self._registry,
            strategy=case.policy_strategy,
            mcp_enabled=self._mcp_enabled,
            mcp_tool_prefix=self._mcp_prefix,
        )
        decision = engine.decide(
            tool_hint=case.tool_hint,
            task=case.task,
            query=case.query,
        )

        selected = decision.selected_tool
        provider = decision.selected_provider.value
        family = decision.tool_family.value

        fallback_used = decision.fallback_used
        fallback_success: bool | None = None
        if case.simulate_mcp_failure and selected and selected.startswith(self._mcp_prefix):
            fallback_used = True
            if decision.fallback_candidates:
                fb = decision.fallback_candidates[0]
                if self._registry.has(fb):
                    selected = fb
                    provider = tool_provider(fb).value
                    family = tool_family(fb).value
                    fallback_success = True
                else:
                    fallback_success = False

        tool_match = case.expected_tool is None or selected == case.expected_tool
        family_match = family == case.expected_tool_family
        provider_match = provider == case.expected_provider

        return ToolRoutingCaseResult(
            case_id=case.id,
            selected_tool=selected,
            selected_provider=provider,
            tool_family=family,
            tool_selection_match=tool_match,
            family_match=family_match,
            provider_match=provider_match,
            fallback_used=fallback_used,
            fallback_success=fallback_success,
            confidence=decision.confidence,
            reason=decision.reason,
            policy_name=decision.policy_name,
        ), decision

    def _evaluate_multi_tool_case(
        self,
        case: ToolRoutingCase,
    ) -> tuple[ToolRoutingCaseResult, ToolPolicyDecision | None]:
        engine = ToolPolicyEngine(
            self._registry,
            strategy=case.policy_strategy,
            mcp_enabled=self._mcp_enabled,
            mcp_tool_prefix=self._mcp_prefix,
        )
        hints = case.tool_hints or [None] * len(case.tasks or [])
        expected_tools = case.expected_tools or []
        expected_families = case.expected_tool_families or []

        selected_tools: list[str] = []
        selected_families: list[str] = []
        selected_providers: list[str] = []
        confidences: list[float] = []
        reasons: list[str] = []

        last_decision: ToolPolicyDecision | None = None
        for idx, task in enumerate(case.tasks or []):
            hint = hints[idx] if idx < len(hints) else None
            decision = engine.decide(tool_hint=hint, task=task, query=case.query)
            last_decision = decision
            if decision.selected_tool:
                selected_tools.append(decision.selected_tool)
                selected_families.append(decision.tool_family.value)
                selected_providers.append(decision.selected_provider.value)
            confidences.append(decision.confidence)
            reasons.append(decision.reason)

        expected_set = set(expected_tools)
        selected_set = set(selected_tools)
        expected_family_set = set(expected_families)
        selected_family_set = set(selected_families)

        tool_recall = len(expected_set & selected_set) / len(expected_set) if expected_set else 0.0
        tool_precision = len(expected_set & selected_set) / len(selected_set) if selected_set else 0.0
        family_recall = (
            len(expected_family_set & selected_family_set) / len(expected_family_set)
            if expected_family_set
            else 0.0
        )
        provider_recall = (
            sum(1 for p in selected_providers if p == case.expected_provider)
            / len(selected_providers)
            if selected_providers
            else 0.0
        )

        primary_provider = (
            case.expected_provider
            if all(p == case.expected_provider for p in selected_providers)
            else (selected_providers[0] if selected_providers else "unknown")
        )

        return ToolRoutingCaseResult(
            case_id=case.id,
            selected_tool=selected_tools[0] if selected_tools else None,
            selected_tools=selected_tools,
            selected_provider=primary_provider,
            tool_family=selected_families[0] if selected_families else "unknown",
            tool_selection_match=tool_recall == 1.0 and tool_precision == 1.0,
            family_match=family_recall == 1.0,
            provider_match=provider_recall == 1.0,
            confidence=sum(confidences) / len(confidences) if confidences else 0.0,
            reason=" | ".join(reasons[:3]),
            policy_name=str(case.policy_strategy),
            is_multi_tool=True,
            tool_recall=round(tool_recall, 4),
            tool_precision=round(tool_precision, 4),
            family_recall=round(family_recall, 4),
            provider_recall=round(provider_recall, 4),
        ), last_decision

    @staticmethod
    def _aggregate_multi_tool_metrics(
        results: list[ToolRoutingCaseResult],
    ) -> MultiToolMetrics | None:
        if not results:
            return None
        return MultiToolMetrics(
            case_count=len(results),
            average_tool_recall=sum(r.tool_recall or 0.0 for r in results) / len(results),
            average_tool_precision=sum(r.tool_precision or 0.0 for r in results) / len(results),
            average_family_recall=sum(r.family_recall or 0.0 for r in results) / len(results),
            average_provider_recall=sum(r.provider_recall or 0.0 for r in results) / len(results),
        )

    @staticmethod
    def _rank_cases(
        results: list[ToolRoutingCaseResult],
        *,
        best: bool,
        limit: int = 3,
    ) -> list[str]:
        def score(item: ToolRoutingCaseResult) -> float:
            base = float(item.tool_selection_match) + float(item.family_match) + item.confidence
            if item.is_multi_tool:
                base += (item.tool_recall or 0.0) + (item.tool_precision or 0.0)
            return base

        ordered = sorted(results, key=score, reverse=best)
        return [item.case_id for item in ordered[:limit]]

    @staticmethod
    def report_to_dict(report: ToolRoutingEvalReport) -> dict[str, Any]:
        payload = report.model_dump(mode="json")
        payload["summary"] = report.model_dump_summary()
        return payload
