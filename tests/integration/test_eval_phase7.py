"""Phase 7 evaluation integration tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agents.planner import PlannerAgent
from config.settings import Settings
from core.llm.rule_based import RuleBasedLLMClient
from eval.loader import KNOWN_DATASETS, load_dataset, list_datasets
from eval.models import CaseScore, EvalCase, EvalCaseResult, EvalRunReport
from eval.regression import RegressionGuard
from eval.runner import EvaluationRunner
from eval.scorer import EvaluationScorer
from eval.store import EvalStore
from graph.runtime.deps import RuntimeDependencies
from graph.runtime.runner import GraphRuntimeRunner
from memory.composite import CompositeMemory
from observability.bootstrap import build_observability, wire_tool_tracer, wrap_llm_client
from plan.execution_critic import ExecutionCritic
from plan.executor import PlanExecutor
from plan.replanning_controller import ReplanningController
from plan.resolver import StepToolResolver
from plan.validator import PlanValidator
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from tools.reliability import ToolReliabilityPolicy
from tools.router import ToolSelectionRouter


@pytest.fixture
async def eval_system(tmp_path):
    settings = Settings(
        metrics_enabled=True,
        eval_enabled=True,
        eval_store_path=str(tmp_path / "eval"),
        eval_regression_threshold=-0.05,
    )
    registry = ToolRegistry.default()
    observability = build_observability(settings)
    assert observability.collector is not None
    await observability.collector.start()

    llm = wrap_llm_client(RuleBasedLLMClient(), observability, settings=settings)
    tool_executor = ToolExecutor(registry, reliability=ToolReliabilityPolicy(max_retries=0))
    callbacks = []
    if observability.observer is not None:
        callbacks.append(observability.observer.on_tool_record)
    wire_tool_tracer(tool_executor, callbacks=callbacks)

    planner = PlannerAgent(llm, tool_registry=registry)
    validator = PlanValidator(registry)
    resolver = StepToolResolver()
    plan_executor = PlanExecutor(
        tool_executor,
        planner=planner,
        validator=validator,
        resolver=resolver,
        summarizer=planner.llm,
    )
    deps = RuntimeDependencies(
        planner=planner,
        tool_router=ToolSelectionRouter(registry),
        plan_executor=plan_executor,
        critic=ExecutionCritic(planner.llm),
        replanner=ReplanningController(planner, validator),
        resolver=resolver,
        validator=validator,
        memory_store=CompositeMemory(),
    )
    runner = GraphRuntimeRunner(deps, metrics_observer=observability.observer)
    store = EvalStore(settings.eval_store_path)
    scorer = EvaluationScorer(weights=settings.eval_score_weights)
    eval_runner = EvaluationRunner(
        runner,
        store,
        scorer,
        profile_service=observability.profile_service,
        metrics_collector=observability.collector,
    )
    regression = RegressionGuard(store, threshold=settings.eval_regression_threshold)
    yield eval_runner, store, scorer, regression, observability
    await observability.collector.stop()


def test_dataset_loading() -> None:
    datasets = list_datasets()
    assert set(KNOWN_DATASETS).issubset(set(datasets))

    travel = load_dataset("travel_eval")
    assert len(travel) >= 3
    assert travel[0].id
    assert travel[0].query
    assert travel[0].expected_tools
    assert travel[0].difficulty in {"easy", "medium", "hard"}


@pytest.mark.asyncio
async def test_batch_evaluation(eval_system) -> None:
    eval_runner, store, _scorer, _regression, _obs = eval_system
    report = await eval_runner.run_dataset(
        "travel_eval",
        seed=42,
        case_ids=["travel-001"],
    )

    assert report.case_count == 1
    assert report.aggregate_score > 0
    assert report.cases[0].final_result
    assert report.cases[0].execution_trace
    assert report.cases[0].graph_trace
    assert report.cases[0].scores.total_score > 0
    assert store.get_run(report.run_id) is not None


def test_scoring_correctness() -> None:
    scorer = EvaluationScorer()
    case = EvalCase(
        id="test-001",
        query="规划上海3日游并计算预算",
        expected_tools=["weather", "budget"],
        expected_output_schema={"min_steps": 2, "required_keywords": ["上海", "预算"]},
        difficulty="medium",
    )
    result = EvalCaseResult(
        case_id="test-001",
        query=case.query,
        final_result="上海3日游预算约5000元",
        execution_trace=[
            {"step_id": 1, "tool_name": "weather", "success": True},
            {"step_id": 2, "tool_name": "budget", "success": True},
        ],
        graph_trace=[],
        tools_used=["budget", "weather"],
        latency_metrics={
            "plan": {
                "goal": "上海3日游",
                "steps": [
                    {"id": 1, "task": "查天气", "tool_hint": "weather"},
                    {"id": 2, "task": "算预算", "tool_hint": "budget"},
                    {"id": 3, "task": "汇总", "tool_hint": "budget"},
                ],
            },
            "execution_critique": {"goal_completed": True, "need_replan": False},
        },
        cost_metrics={"total_estimated_cost_usd": 0.005},
    )

    scores = scorer.score_case(case, result)
    assert scores.tool_accuracy == 1.0
    assert scores.plan_quality >= 0.8
    assert scores.execution_success >= 0.9
    assert scores.cost_efficiency > 0.5
    assert scores.total_score >= 0.8


def test_regression_detection(tmp_path) -> None:
    store = EvalStore(str(tmp_path / "eval-regression"))
    guard = RegressionGuard(store, threshold=-0.05)

    baseline = EvalRunReport(
        run_id="baseline-run",
        dataset="travel_eval",
        seed=42,
        case_count=1,
        aggregate_score=0.9,
        aggregate_scores=CaseScore(total_score=0.9),
        cases=[
            EvalCaseResult(
                case_id="travel-001",
                query="规划上海3日游",
                scores=CaseScore(total_score=0.9),
            ),
        ],
        finished_at=datetime.now(UTC),
    )
    guard.save_baseline(baseline)

    current = EvalRunReport(
        run_id="current-run",
        dataset="travel_eval",
        seed=42,
        case_count=1,
        aggregate_score=0.7,
        aggregate_scores=CaseScore(total_score=0.7),
        cases=[
            EvalCaseResult(
                case_id="travel-001",
                query="规划上海3日游",
                scores=CaseScore(total_score=0.7),
            ),
        ],
        finished_at=datetime.now(UTC),
    )
    store.save_run(current)

    report = guard.compare(current=current)
    assert report.regression_detected is True
    assert report.delta_score == pytest.approx(-0.2, abs=0.001)
    assert report.per_case_diff[0]["regressed"] is True


@pytest.mark.asyncio
async def test_eval_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EVAL_ENABLED", "true")
    monkeypatch.setenv("METRICS_ENABLED", "true")
    monkeypatch.setenv("EVAL_STORE_PATH", str(tmp_path / "eval-api"))
    from config.settings import get_settings

    get_settings.cache_clear()

    from app.container import ApplicationContainer
    from app.main import create_app
    from config.env_loader import bootstrap_environment
    from httpx import ASGITransport, AsyncClient

    bootstrap_environment()
    app = create_app()
    container = ApplicationContainer.create()
    await container.startup()
    container.bind_app_state(app)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        run_resp = await client.post(
            "/api/v1/eval/run",
            json={
                "dataset": "travel_eval",
                "seed": 42,
                "case_ids": ["travel-001"],
                "save_baseline": True,
            },
        )
        assert run_resp.status_code == 200
        body = run_resp.json()
        payload = body["data"] if "data" in body else body
        assert payload["aggregate_score"] > 0
        run_id = payload["run_id"]

        report_resp = await client.get("/api/v1/eval/report", params={"run_id": run_id})
        assert report_resp.status_code == 200
        report_body = report_resp.json()
        report_payload = report_body["data"] if "data" in report_body else report_body
        assert report_payload["run_id"] == run_id

        regression_resp = await client.get("/api/v1/eval/regression")
        assert regression_resp.status_code == 200
        regression_body = regression_resp.json()
        regression = regression_body["data"] if "data" in regression_body else regression_body
        assert regression["regression_detected"] is False

    if container.observability.collector is not None:
        await container.observability.collector.stop()
