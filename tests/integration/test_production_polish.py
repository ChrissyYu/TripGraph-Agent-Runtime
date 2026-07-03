"""Phase 8 production polish: detailed health and JSON logging."""

from __future__ import annotations

import json
import logging
from io import StringIO

import pytest

from observability.context import current_trace_id
from observability.logging.json_logger import JsonLogFormatter, log_json
from observability.logging.structured import log_event


@pytest.mark.asyncio
async def test_health_detailed_endpoint(async_client) -> None:
    response = await async_client.get("/api/v1/health/detailed")
    assert response.status_code == 200
    body = response.json()

    assert body["status"] in {"healthy", "degraded", "unhealthy"}
    assert body["version"]
    assert "components" in body

    components = body["components"]
    for name in ("llm", "graph_runtime", "tool_registry", "persistence", "observability"):
        assert name in components
        assert "status" in components[name]

    llm = components["llm"]
    assert llm["status"] in {"healthy", "unhealthy"}
    assert "latency_ms" in llm

    tools = components["tool_registry"]
    assert tools["tool_count"] > 0
    assert isinstance(tools["tools"], list)


def test_json_log_format_validation() -> None:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())

    logger = logging.getLogger("graph_runtime")
    logger.handlers.clear()
    logger.propagate = False
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    log_json(
        "graph_runtime",
        "node_execute",
        node="planner",
        latency_ms=12.3,
        execution_id="exec-123",
    )

    payload = json.loads(stream.getvalue().strip())
    assert payload["level"] == "INFO"
    assert payload["module"] == "graph_runtime"
    assert payload["event"] == "node_execute"
    assert payload["node"] == "planner"
    assert payload["latency_ms"] == 12.3
    assert payload["execution_id"] == "exec-123"
    assert "timestamp" in payload
    assert "trace_id" in payload


def test_trace_id_propagation_in_json_logs() -> None:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())

    logger = logging.getLogger("observability.events")
    logger.handlers.clear()
    logger.propagate = False
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    token = current_trace_id.set("trace-test-001")
    try:
        log_event("node_execute", node_id="planner", latency_ms=5.0)
    finally:
        current_trace_id.reset(token)

    payload = json.loads(stream.getvalue().strip())
    assert payload["trace_id"] == "trace-test-001"
    assert payload["event"] == "node_execute"
    assert payload["node"] == "planner"
    assert payload["latency_ms"] == 5.0


def test_enable_json_log_wires_json_formatter(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_JSON_LOG", "true")
    from config.settings import get_settings

    get_settings.cache_clear()

    from core.logging import setup_logging

    setup_logging("INFO", json_format=get_settings().enable_json_log)

    root = logging.getLogger()
    assert root.handlers
    assert isinstance(root.handlers[0].formatter, JsonLogFormatter)

    get_settings.cache_clear()
