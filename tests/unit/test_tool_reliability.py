"""Unit tests for ToolExecutor reliability (retry / timeout / fallback)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from core.exceptions import ToolTimeoutError
from tools.builtin.echo import echo_tool
from tools.builtin.weather import weather_tool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from tools.reliability import ToolReliabilityPolicy
from tools.tracing import ToolTracer


class FlakyTool:
    """Fails a configurable number of times before succeeding."""

    name = "flaky"
    description = "Flaky tool for retry tests"
    input_schema = weather_tool._tool_instance.input_schema

    def __init__(self, fail_times: int = 1) -> None:
        self._fail_times = fail_times
        self._calls = 0

    async def run(self, args: dict[str, Any]) -> dict[str, Any]:
        self._calls += 1
        if self._calls <= self._fail_times:
            raise RuntimeError(f"transient failure #{self._calls}")
        return {"city": args.get("city", "unknown"), "recovered": True}


class SlowTool:
    """Hangs longer than the configured timeout."""

    name = "slow"
    description = "Slow tool for timeout tests"
    input_schema = echo_tool._tool_instance.input_schema

    async def run(self, args: dict[str, Any]) -> str:
        await asyncio.sleep(0.2)
        return "too late"


@pytest.fixture
def tracer() -> ToolTracer:
    return ToolTracer(session_id="reliability-test", debug=False)


def _registry_with(*tools) -> Mock:
    mapping = {t.name: t for t in tools}
    registry = Mock(spec=ToolRegistry)
    registry.get.side_effect = lambda name: mapping[name] if name in mapping else (_ for _ in ()).throw(
        KeyError(f"Unknown tool: {name}"),
    )
    return registry


def _executor(
    registry: Mock,
    tracer: ToolTracer,
    *,
    max_retries: int = 2,
    timeout_sec: float | None = 30.0,
    fallback_tools: dict[str, str] | None = None,
) -> ToolExecutor:
    return ToolExecutor(
        registry,
        tracer=tracer,
        reliability=ToolReliabilityPolicy(
            max_retries=max_retries,
            timeout_sec=timeout_sec,
            fallback_tools=fallback_tools or {},
        ),
    )


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt(tracer: ToolTracer) -> None:
    flaky = FlakyTool(fail_times=1)
    executor = _executor(_registry_with(flaky), tracer, max_retries=2)

    obs = await executor.execute_llm_call({"tool": "flaky", "args": {"city": "上海"}})

    assert obs.success is True
    assert obs.output["recovered"] is True
    assert flaky._calls == 2

    attempts = [r for r in tracer.records if r.tool_name == "flaky"]
    assert len(attempts) == 2
    assert attempts[0].success is False
    assert attempts[0].attempt == 1
    assert attempts[1].success is True
    assert attempts[1].attempt == 2
    assert attempts[0].error is not None


@pytest.mark.asyncio
async def test_retry_exhausted_records_all_failures(tracer: ToolTracer) -> None:
    flaky = FlakyTool(fail_times=5)
    executor = _executor(_registry_with(flaky), tracer, max_retries=2)

    obs = await executor.execute_llm_call({"tool": "flaky", "args": {"city": "上海"}})

    assert obs.success is False
    assert flaky._calls == 3  # 1 initial + 2 retries

    attempts = [r for r in tracer.records if r.tool_name == "flaky"]
    assert len(attempts) == 3
    assert all(not r.success for r in attempts)
    assert [r.attempt for r in attempts] == [1, 2, 3]
    assert all(r.error is not None for r in attempts)


@pytest.mark.asyncio
async def test_timeout_records_failure_in_trace(tracer: ToolTracer) -> None:
    slow = SlowTool()
    executor = _executor(_registry_with(slow), tracer, max_retries=0, timeout_sec=0.05)

    obs = await executor.execute_llm_call({"tool": "slow", "args": {"message": "hi"}})

    assert obs.success is False
    assert "timed out" in (obs.error or "").lower()

    record = tracer.records[0]
    assert record.tool_name == "slow"
    assert record.success is False
    assert "timed out" in (record.error or "").lower()


@pytest.mark.asyncio
async def test_fallback_invoked_after_primary_exhausted(tracer: ToolTracer) -> None:
    flaky = FlakyTool(fail_times=10)
    registry = _registry_with(flaky, weather_tool._tool_instance)
    executor = _executor(
        registry,
        tracer,
        max_retries=1,
        fallback_tools={"flaky": "weather"},
    )

    obs = await executor.execute_llm_call({"tool": "flaky", "args": {"city": "上海"}})

    assert obs.success is True
    assert obs.tool == "flaky"
    assert obs.output["city"] == "上海"

    flaky_attempts = [r for r in tracer.records if r.tool_name == "flaky"]
    fallback_attempts = [r for r in tracer.records if r.tool_name == "weather" and r.is_fallback]
    assert len(flaky_attempts) == 2
    assert all(not r.success for r in flaky_attempts)
    assert len(fallback_attempts) == 1
    assert fallback_attempts[0].success is True
    assert fallback_attempts[0].original_tool == "flaky"
    assert fallback_attempts[0].is_fallback is True


@pytest.mark.asyncio
async def test_fallback_also_retries_on_failure(tracer: ToolTracer) -> None:
    flaky_primary = FlakyTool(fail_times=10)
    flaky_fallback = FlakyTool(fail_times=10)
    flaky_fallback.name = "weather"

    registry = Mock(spec=ToolRegistry)
    registry.get.side_effect = lambda name: {
        "flaky": flaky_primary,
        "weather": flaky_fallback,
    }[name]

    executor = _executor(
        registry,
        tracer,
        max_retries=1,
        fallback_tools={"flaky": "weather"},
    )

    obs = await executor.execute_llm_call({"tool": "flaky", "args": {"city": "上海"}})

    assert obs.success is False
    assert obs.tool == "flaky"

    primary_traces = [r for r in tracer.records if r.tool_name == "flaky"]
    fallback_traces = [r for r in tracer.records if r.tool_name == "weather"]
    assert len(primary_traces) == 2
    assert len(fallback_traces) == 2
    assert all(r.is_fallback for r in fallback_traces)
    assert all(not r.success for r in primary_traces + fallback_traces)


@pytest.mark.asyncio
async def test_export_trace_includes_retry_metadata(tracer: ToolTracer) -> None:
    flaky = FlakyTool(fail_times=1)
    executor = _executor(_registry_with(flaky), tracer, max_retries=2)

    await executor.execute_llm_call({"tool": "flaky", "args": {"city": "上海"}})

    import json

    log = json.loads(executor.export_trace_json())
    assert log["record_count"] == 2
    assert log["records"][0]["success"] is False
    assert log["records"][0]["attempt"] == 1
    assert log["records"][1]["success"] is True
    assert log["records"][1]["attempt"] == 2
