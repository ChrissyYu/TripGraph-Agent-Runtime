"""Evaluation system bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from config.settings import Settings
from eval.regression import RegressionGuard
from eval.runner import EvaluationRunner
from eval.scorer import EvaluationScorer
from eval.store import EvalStore

if TYPE_CHECKING:
    from graph.runtime.runner import GraphRuntimeRunner
    from observability.bootstrap import ObservabilityBundle


@dataclass
class EvalBundle:
    enabled: bool
    store: EvalStore | None = None
    scorer: EvaluationScorer | None = None
    runner: EvaluationRunner | None = None
    regression: RegressionGuard | None = None


def build_eval_system(
    settings: Settings,
    graph_runner: GraphRuntimeRunner,
    observability: ObservabilityBundle | None = None,
) -> EvalBundle:
    if not settings.eval_enabled:
        return EvalBundle(enabled=False)

    store = EvalStore(settings.eval_store_path)
    scorer = EvaluationScorer(weights=settings.eval_score_weights)
    profile_service = observability.profile_service if observability else None
    metrics_collector = observability.collector if observability else None

    runner = EvaluationRunner(
        graph_runner,
        store,
        scorer,
        profile_service=profile_service,
        metrics_collector=metrics_collector,
    )
    regression = RegressionGuard(store, threshold=settings.eval_regression_threshold)
    return EvalBundle(
        enabled=True,
        store=store,
        scorer=scorer,
        runner=runner,
        regression=regression,
    )
