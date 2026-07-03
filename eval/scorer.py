"""Evaluation scoring engine."""

from __future__ import annotations

from typing import Any

from eval.models import CaseScore, EvalCase, EvalCaseResult, EvalRunReport

DEFAULT_WEIGHTS = {
    "tool_accuracy": 0.30,
    "plan_quality": 0.25,
    "execution_success": 0.30,
    "cost_efficiency": 0.15,
}

DIFFICULTY_COST_CEILING = {
    "easy": 0.01,
    "medium": 0.02,
    "hard": 0.05,
}


class EvaluationScorer:
    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self._weights = weights or DEFAULT_WEIGHTS

    def score_case(self, case: EvalCase, result: EvalCaseResult) -> CaseScore:
        if result.error:
            return CaseScore()

        tool_accuracy = self._score_tool_accuracy(case, result)
        plan_quality = self._score_plan_quality(case, result)
        execution_success = self._score_execution_success(result)
        cost_efficiency = self._score_cost_efficiency(case, result)

        total = (
            self._weights["tool_accuracy"] * tool_accuracy
            + self._weights["plan_quality"] * plan_quality
            + self._weights["execution_success"] * execution_success
            + self._weights["cost_efficiency"] * cost_efficiency
        )
        return CaseScore(
            tool_accuracy=round(tool_accuracy, 4),
            plan_quality=round(plan_quality, 4),
            execution_success=round(execution_success, 4),
            cost_efficiency=round(cost_efficiency, 4),
            total_score=round(total, 4),
        )

    def score_run(self, report: EvalRunReport, cases: list[EvalCase]) -> EvalRunReport:
        case_map = {item.id: item for item in cases}
        scored_cases: list[EvalCaseResult] = []
        dimension_totals = {key: 0.0 for key in DEFAULT_WEIGHTS}
        total_score_sum = 0.0
        passed = 0

        for result in report.cases:
            case = case_map.get(result.case_id)
            if case is None:
                scored_cases.append(result)
                continue
            scores = self.score_case(case, result)
            result.scores = scores
            scored_cases.append(result)
            total_score_sum += scores.total_score
            if scores.total_score >= 0.6:
                passed += 1
            dimension_totals["tool_accuracy"] += scores.tool_accuracy
            dimension_totals["plan_quality"] += scores.plan_quality
            dimension_totals["execution_success"] += scores.execution_success
            dimension_totals["cost_efficiency"] += scores.cost_efficiency

        count = len(scored_cases) or 1
        report.cases = scored_cases
        report.passed_count = passed
        report.aggregate_score = round(total_score_sum / count, 4)
        report.aggregate_scores = CaseScore(
            tool_accuracy=round(dimension_totals["tool_accuracy"] / count, 4),
            plan_quality=round(dimension_totals["plan_quality"] / count, 4),
            execution_success=round(dimension_totals["execution_success"] / count, 4),
            cost_efficiency=round(dimension_totals["cost_efficiency"] / count, 4),
            total_score=report.aggregate_score,
        )
        return report

    @staticmethod
    def _score_tool_accuracy(case: EvalCase, result: EvalCaseResult) -> float:
        expected = set(case.expected_tools)
        actual = set(result.tools_used)
        if not expected:
            return 1.0 if actual else 0.5
        if not actual:
            return 0.0
        matched = len(expected & actual)
        return matched / len(expected)

    @staticmethod
    def _score_plan_quality(case: EvalCase, result: EvalCaseResult) -> float:
        schema = case.expected_output_schema
        min_steps = int(schema.get("min_steps", 2))
        keywords = schema.get("required_keywords", [])

        score = 0.0
        plan = _extract_plan(result)
        if plan is None:
            return 0.0

        if plan.get("goal"):
            score += 0.3

        steps = plan.get("steps") or []
        if len(steps) >= min_steps:
            score += 0.3
        if len(steps) >= 3:
            score += 0.2

        text_blob = f"{plan.get('goal', '')} {result.final_result}".lower()
        if keywords:
            matched = sum(1 for keyword in keywords if keyword.lower() in text_blob)
            score += 0.2 * (matched / len(keywords))
        else:
            score += 0.2

        return min(score, 1.0)

    @staticmethod
    def _score_execution_success(result: EvalCaseResult) -> float:
        traces = result.execution_trace
        if not traces:
            return 0.0

        successes = [item.get("success") for item in traces if "success" in item]
        if not successes:
            return 0.0

        trace_score = sum(1 for success in successes if success) / len(successes)
        score = trace_score * 0.5

        critique = _extract_critique(result)
        if critique is None:
            score += 0.25
        elif critique.get("goal_completed"):
            score += 0.5
        elif critique.get("need_replan") is False:
            score += 0.35
        else:
            score += 0.15

        return min(score, 1.0)

    @staticmethod
    def _score_cost_efficiency(case: EvalCase, result: EvalCaseResult) -> float:
        cost = float(result.cost_metrics.get("total_estimated_cost_usd", 0.0) or 0.0)
        if cost <= 0:
            return 1.0
        ceiling = DIFFICULTY_COST_CEILING.get(case.difficulty, 0.02)
        return max(0.0, min(1.0, 1.0 - cost / ceiling))


def _extract_plan(result: EvalCaseResult) -> dict[str, Any] | None:
    plan = result.latency_metrics.get("plan")
    if isinstance(plan, dict):
        return plan
    return None


def _extract_critique(result: EvalCaseResult) -> dict[str, Any] | None:
    critique = result.latency_metrics.get("execution_critique")
    if isinstance(critique, dict):
        return critique
    return None
