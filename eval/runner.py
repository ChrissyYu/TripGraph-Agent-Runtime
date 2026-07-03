"""Batch evaluation runner for GraphRuntime."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from eval.loader import load_dataset
from eval.models import EvalCaseResult, EvalRunReport
from eval.scorer import EvaluationScorer
from eval.store import EvalStore
from graph.runtime.execution_policy import ExecutionPolicy

if TYPE_CHECKING:
    from graph.runtime.runner import GraphRuntimeRunner
    from observability.metrics.collector import MetricsCollector
    from observability.profile import ExecutionProfileService


class EvaluationRunner:
    """External evaluation layer over GraphRuntimeRunner."""

    def __init__(
        self,
        runner: GraphRuntimeRunner,
        store: EvalStore,
        scorer: EvaluationScorer,
        *,
        profile_service: ExecutionProfileService | None = None,
        metrics_collector: MetricsCollector | None = None,
    ) -> None:
        self._runner = runner
        self._store = store
        self._scorer = scorer
        self._profile_service = profile_service
        self._metrics_collector = metrics_collector

    async def run_dataset(
        self,
        dataset: str,
        *,
        seed: int = 42,
        run_id: str | None = None,
        case_ids: list[str] | None = None,
    ) -> EvalRunReport:
        cases = load_dataset(dataset)
        if case_ids:
            allowed = set(case_ids)
            cases = [case for case in cases if case.id in allowed]

        report = EvalRunReport(
            run_id=run_id or str(uuid4()),
            dataset=dataset,
            seed=seed,
            case_count=len(cases),
            metadata={"deterministic": dataset != "real_llm/qwen_smoke"},
        )

        results: list[EvalCaseResult] = []
        for index, case in enumerate(cases):
            session_id = f"eval-{report.run_id}-{case.id}"
            policy = ExecutionPolicy(capture_state_snapshots=True).with_seed(seed + index)

            try:
                response = await self._runner.invoke(
                    case.query,
                    session_id=session_id,
                    policy=policy,
                )
                if self._metrics_collector is not None:
                    await self._metrics_collector.drain()

                case_result = self._build_case_result(case, response)
                if response.execution_id and self._profile_service is not None:
                    profile = self._profile_service.get_profile(response.execution_id)
                    if profile:
                        case_result.cost_metrics = {
                            "total_tokens": profile.get("total_tokens", 0),
                            "total_estimated_cost_usd": profile.get("total_estimated_cost_usd", 0.0),
                            "cost_breakdown": profile.get("cost_breakdown", {}),
                        }
                        case_result.latency_metrics = {
                            "total_latency_ms": profile.get("total_latency_ms", 0.0),
                            "graph_execution_time_ms": profile.get("graph_execution_time_ms"),
                            "node_breakdown": profile.get("node_breakdown", []),
                            "tool_breakdown": profile.get("tool_breakdown", []),
                            "bottleneck_node": profile.get("bottleneck_node"),
                        }

                case_result.execution_id = response.execution_id
                results.append(case_result)
            except Exception as exc:
                results.append(
                    EvalCaseResult(
                        case_id=case.id,
                        query=case.query,
                        error=str(exc),
                    ),
                )

        report.cases = results
        report.finished_at = datetime.now(UTC)
        report = self._scorer.score_run(report, cases)
        self._store.save_run(report)
        return report

    @staticmethod
    def _build_case_result(case, response) -> EvalCaseResult:
        tools_used = sorted(
            {
                entry.tool_name
                for entry in response.execution_trace
                if entry.tool_name
            },
        )
        return EvalCaseResult(
            case_id=case.id,
            query=case.query,
            final_result=response.final_result,
            execution_trace=[entry.model_dump(mode="json") for entry in response.execution_trace],
            graph_trace=[entry.model_dump(mode="json") for entry in response.graph_trace],
            tools_used=tools_used,
            latency_metrics={
                "node_timeline": [entry.model_dump(mode="json") for entry in response.node_timeline],
                "plan": response.plan.model_dump(mode="json") if response.plan else None,
                "execution_critique": (
                    response.execution_critique.model_dump(mode="json")
                    if response.execution_critique
                    else None
                ),
            },
        )

    def get_report(self, run_id: str | None = None) -> EvalRunReport | None:
        if run_id:
            return self._store.get_run(run_id)
        return self._store.get_latest_run()
