"""Phase 6 observability integration tests."""

from __future__ import annotations

import pytest

from agents.planner import PlannerAgent
from config.settings import Settings
from core.llm.rule_based import RuleBasedLLMClient
from graph.runtime.deps import RuntimeDependencies
from graph.runtime.execution_policy import ExecutionPolicy
from graph.runtime.runner import GraphRuntimeRunner
from memory.composite import CompositeMemory
from observability.bootstrap import build_observability, wire_tool_tracer, wrap_llm_client
from observability.profile import ExecutionProfileService
from plan.execution_critic import ExecutionCritic
from plan.executor import PlanExecutor
from plan.replanning_controller import ReplanningController
from plan.resolver import StepToolResolver
from plan.validator import PlanValidator
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from tools.reliability import ToolReliabilityPolicy
from tools.router import ToolSelectionRouter

USER_QUERY = "规划上海3日游并计算预算"


@pytest.fixture
async def metrics_runner(tmp_path):
    settings = Settings(
        metrics_enabled=True,
        metrics_prompt_usd_per_1k=0.005,
        metrics_completion_usd_per_1k=0.015,
    )
    registry = ToolRegistry.default()
    bundle = build_observability(settings)
    assert bundle.collector is not None
    await bundle.collector.start()

    llm = wrap_llm_client(RuleBasedLLMClient(), bundle, settings=settings)
    tool_executor = ToolExecutor(registry, reliability=ToolReliabilityPolicy(max_retries=1))
    callbacks = []
    if bundle.observer is not None:
        callbacks.append(bundle.observer.on_tool_record)
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
    runner = GraphRuntimeRunner(deps, metrics_observer=bundle.observer)
    profile_service = ExecutionProfileService(bundle.store)
    yield runner, bundle, profile_service
    await bundle.collector.stop()


async def _run_and_drain(runner: GraphRuntimeRunner, bundle, session_id: str):
    result = await runner.invoke(
        USER_QUERY,
        session_id=session_id,
        policy=ExecutionPolicy(capture_state_snapshots=True),
    )
    assert bundle.collector is not None
    await bundle.collector.drain()
    return result


@pytest.mark.asyncio
async def test_metrics_collection_correctness(metrics_runner) -> None:
    runner, bundle, _profile = metrics_runner
    result = await _run_and_drain(runner, bundle, "metrics-basic")

    assert result.execution_id is not None
    metrics = bundle.store.get(result.execution_id)
    assert metrics is not None
    assert metrics.graph_execution_time_ms is not None
    assert metrics.graph_execution_time_ms > 0
    assert len(metrics.nodes) >= 5
    assert len(metrics.tools) >= 2
    assert len(metrics.llm_calls) >= 2
    assert metrics.tool_success_rate > 0
    assert metrics.total_llm_tokens > 0
    assert metrics.total_estimated_cost_usd > 0


@pytest.mark.asyncio
async def test_latency_aggregation(metrics_runner) -> None:
    runner, bundle, profile_service = metrics_runner
    result = await _run_and_drain(runner, bundle, "metrics-latency")

    profile = profile_service.get_profile(result.execution_id)
    assert profile is not None
    assert profile["total_latency_ms"] > 0
    assert profile["node_breakdown"]
    assert profile["tool_breakdown"]
    assert sum(item["total_latency_ms"] for item in profile["node_breakdown"]) > 0
    assert profile["bottleneck_node"] is not None
    assert profile["bottleneck_node"]["latency_ms"] > 0


@pytest.mark.asyncio
async def test_cost_tracking_accuracy(metrics_runner) -> None:
    runner, bundle, profile_service = metrics_runner
    result = await _run_and_drain(runner, bundle, "metrics-cost")

    metrics = bundle.store.get(result.execution_id)
    profile = profile_service.get_profile(result.execution_id)
    assert metrics is not None and profile is not None

    llm_total = sum(call.total_tokens for call in metrics.llm_calls)
    assert profile["total_tokens"] == llm_total
    assert profile["cost_breakdown"]["prompt_tokens"] == sum(
        call.prompt_tokens for call in metrics.llm_calls
    )
    assert profile["cost_breakdown"]["completion_tokens"] == sum(
        call.completion_tokens for call in metrics.llm_calls
    )

    callers = {item["caller"] for item in profile["llm_breakdown"]}
    assert "planner" in callers
    assert "critic" in callers

    expected_cost = sum(call.estimated_cost_usd for call in metrics.llm_calls)
    assert profile["total_estimated_cost_usd"] == round(expected_cost, 6)


@pytest.mark.asyncio
async def test_execution_profiling_output(metrics_runner) -> None:
    runner, bundle, profile_service = metrics_runner
    result = await _run_and_drain(runner, bundle, "metrics-profile")

    profile = profile_service.get_profile(result.execution_id)
    assert profile is not None
    assert profile["execution_id"] == result.execution_id
    assert profile["status"] == "completed"
    assert profile["retry_count"] >= 0
    assert 0 < profile["tool_success_rate"] <= 1
    assert profile["node_execution_count"] >= 5
    assert profile["tool_call_count"] >= 2
    assert profile["llm_call_count"] >= 2
    assert "by_caller" in profile["cost_breakdown"]


@pytest.mark.asyncio
async def test_execution_profile_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("METRICS_ENABLED", "true")
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
        exec_resp = await client.post(
            "/api/v1/graph_execute",
            json={"session_id": "api-metrics", "query": USER_QUERY},
        )
        assert exec_resp.status_code == 200
        execution_id = exec_resp.json()["execution_id"]
        assert execution_id

        if container.observability.collector is not None:
            await container.observability.collector.drain()

        profile_resp = await client.get(f"/api/v1/execution/{execution_id}/profile")
        assert profile_resp.status_code == 200
        profile_body = profile_resp.json()
        profile = profile_body["data"] if profile_body.get("success") else profile_body
        assert profile["execution_id"] == execution_id
        assert profile["total_latency_ms"] > 0
        assert profile["bottleneck_node"] is not None

    if container.observability.collector is not None:
        await container.observability.collector.stop()
