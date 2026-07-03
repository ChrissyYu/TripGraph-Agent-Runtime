"""Phase 8 deployment integration tests."""

from __future__ import annotations

import pytest

from app.container import ApplicationContainer
from config.env_loader import bootstrap_environment
from eval.loader import load_dataset


@pytest.mark.asyncio
async def test_service_startup_container() -> None:
    bootstrap_environment()
    container = ApplicationContainer.create()
    await container.startup()
    assert container.graph_service is not None
    assert container.plan_service is not None
    assert container.execution_service is not None
    assert container.eval_service.enabled
    await container.shutdown()


@pytest.mark.asyncio
async def test_api_health_and_readiness(async_client) -> None:
    health = await async_client.get("/api/v1/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"

    ready = await async_client.get("/api/v1/ready")
    assert ready.status_code == 200
    ready_body = ready.json()
    assert ready_body["success"] is True
    assert ready_body["data"]["ready"] is True
    assert "features" in ready_body["data"]


@pytest.mark.asyncio
async def test_structured_api_endpoints(async_client) -> None:
    graph = await async_client.post(
        "/api/v1/graph/execute",
        json={"session_id": "phase8-graph", "query": "规划上海3日游并计算预算"},
    )
    assert graph.status_code == 200
    assert graph.json()["runtime"] == "graph"

    plan = await async_client.post(
        "/api/v1/plan/execute",
        json={"session_id": "phase8-plan", "query": "规划上海3日游并计算预算"},
    )
    assert plan.status_code == 200
    assert plan.json()["plan"]["goal"]

    eval_resp = await async_client.post(
        "/api/v1/eval/run",
        json={"dataset": "travel_eval", "seed": 42, "case_ids": ["travel-001"]},
    )
    assert eval_resp.status_code == 200
    eval_body = eval_resp.json()
    assert eval_body["success"] is True
    assert eval_body["data"]["aggregate_score"] > 0


@pytest.mark.asyncio
async def test_legacy_routes_remain_available(async_client) -> None:
    response = await async_client.post(
        "/api/v1/graph_execute",
        json={"session_id": "legacy-graph", "query": "规划上海3日游并计算预算"},
    )
    assert response.status_code == 200
    assert response.json()["final_result"]


def test_docker_env_compatibility_mock(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PERSISTENCE_DB_PATH", str(tmp_path / "persistence" / "executions.db"))
    monkeypatch.setenv("EVAL_STORE_PATH", str(tmp_path / "eval"))
    monkeypatch.setenv("LONG_TERM_STORE_PATH", str(tmp_path / "memory"))
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "8000")
    bootstrap_environment(override=True)

    from config.settings import get_settings

    settings = get_settings()
    assert settings.host == "0.0.0.0"
    assert settings.port == 8000
    assert "executions.db" in settings.persistence_db_path

    cases = load_dataset("travel_eval")
    assert cases
