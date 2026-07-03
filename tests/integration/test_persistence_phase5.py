"""Phase 5 persistence integration tests."""

from __future__ import annotations

import pytest

from agents.planner import PlannerAgent
from config.settings import Settings
from core.llm.rule_based import RuleBasedLLMClient
from graph.runtime.deps import RuntimeDependencies
from graph.runtime.execution_policy import ExecutionPolicy
from graph.runtime.runner import GraphRuntimeRunner
from memory.composite import CompositeMemory
from persistence.bootstrap import bind_runner, build_persistence, wire_tool_tracer
from persistence.db.models import ExecutionStatus
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
async def persisted_runner(tmp_path):
    settings = Settings(
        persistence_enabled=True,
        persistence_db_path=str(tmp_path / "phase5.db"),
    )
    registry = ToolRegistry.default()
    bundle = build_persistence(settings)
    tool_executor = ToolExecutor(registry, reliability=ToolReliabilityPolicy(max_retries=0))
    wire_tool_tracer(tool_executor, bundle)

    planner = PlannerAgent(RuleBasedLLMClient(), tool_registry=registry)
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
    runner = GraphRuntimeRunner(deps, recorder=bundle.recorder)
    bind_runner(bundle, runner)

    assert bundle.writer is not None
    await bundle.writer.start()
    yield runner, bundle
    await bundle.writer.stop()


async def _run_and_drain(runner: GraphRuntimeRunner, bundle, session_id: str):
    policy = ExecutionPolicy(capture_state_snapshots=True)
    result = await runner.invoke(USER_QUERY, session_id=session_id, policy=policy)
    assert bundle.writer is not None
    await bundle.writer.drain()
    return result


@pytest.mark.asyncio
async def test_execution_persistence(persisted_runner) -> None:
    runner, bundle = persisted_runner
    result = await _run_and_drain(runner, bundle, "persist-exec")

    assert result.execution_id is not None
    assert bundle.replay_service is not None
    detail = await bundle.replay_service.get_execution(result.execution_id)
    assert detail is not None
    assert detail["execution"]["status"] == ExecutionStatus.COMPLETED.value
    assert detail["execution"]["session_id"] == "persist-exec"
    assert len(detail["nodes"]) >= 5
    assert detail["execution"]["final_result"] == result.final_result


@pytest.mark.asyncio
async def test_replay_consistency(persisted_runner) -> None:
    runner, bundle = persisted_runner
    result = await _run_and_drain(runner, bundle, "persist-replay")

    assert bundle.replay_service is not None
    replay = await bundle.replay_service.replay_execution(result.execution_id)
    assert replay["mode"] == "full"
    assert replay["consistent"] is True
    assert replay["hash_consistent"] is True
    assert replay["all_replayed"] is True
    assert replay["final_result_match"] is True
    assert replay["replayed_node_count"] == replay["original_node_count"]


@pytest.mark.asyncio
async def test_session_restore(persisted_runner) -> None:
    runner, bundle = persisted_runner
    first = await _run_and_drain(runner, bundle, "persist-restore")

    assert bundle.replay_service is not None
    restored = await bundle.replay_service.restore_session(
        "persist-restore",
        query="继续完善上海行程预算细节",
    )
    assert restored["restored_from_execution_id"] == first.execution_id
    assert restored["result"]["final_result"]
    assert restored["result"]["session_id"] == "persist-restore"


@pytest.mark.asyncio
async def test_tool_call_persistence(persisted_runner) -> None:
    runner, bundle = persisted_runner
    result = await _run_and_drain(runner, bundle, "persist-tools")

    assert bundle.replay_service is not None
    detail = await bundle.replay_service.get_execution(result.execution_id)
    tool_calls = detail["tool_calls"]
    assert len(tool_calls) >= 2
    assert all(call["success"] for call in tool_calls)
    tool_names = {call["tool_name"] for call in tool_calls}
    assert "weather" in tool_names or "budget" in tool_names
    assert all(call["execution_id"] == result.execution_id for call in tool_calls)


@pytest.mark.asyncio
async def test_compare_executions(persisted_runner) -> None:
    runner, bundle = persisted_runner
    first = await _run_and_drain(runner, bundle, "persist-compare-a")
    second = await _run_and_drain(runner, bundle, "persist-compare-b")

    assert bundle.replay_service is not None
    comparison = await bundle.replay_service.replay_execution(
        first.execution_id,
        compare_with=second.execution_id,
    )
    assert "comparison" in comparison
    assert comparison["comparison"]["node_count_match"] is True


@pytest.mark.asyncio
async def test_persistence_api(async_client, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PERSISTENCE_ENABLED", "true")
    monkeypatch.setenv("PERSISTENCE_DB_PATH", str(tmp_path / "api.db"))
    from config.settings import get_settings

    get_settings.cache_clear()

    from app.container import ApplicationContainer
    from app.main import create_app
    from config.env_loader import bootstrap_environment

    bootstrap_environment()
    app = create_app()
    container = ApplicationContainer.create()
    await container.startup()
    container.bind_app_state(app)

    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        exec_resp = await client.post(
            "/api/v1/graph_execute",
            json={"session_id": "api-persist", "query": USER_QUERY, "debug": True},
        )
        assert exec_resp.status_code == 200
        execution_id = exec_resp.json().get("execution_id")
        assert execution_id

        if container.persistence.writer is not None:
            await container.persistence.writer.drain()

        get_resp = await client.get(f"/api/v1/execution/{execution_id}")
        assert get_resp.status_code == 200
        get_body = get_resp.json()
        body = get_body["data"] if get_body.get("success") else get_body
        assert body["execution"]["execution_id"] == execution_id
        assert len(body["nodes"]) >= 5

        replay_resp = await client.post(
            "/api/v1/replay_execution",
            json={"execution_id": execution_id},
        )
        assert replay_resp.status_code == 200
        assert replay_resp.json()["consistent"] is True

    if container.persistence.writer is not None:
        await container.persistence.writer.stop()
