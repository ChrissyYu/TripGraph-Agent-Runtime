"""Unit tests for ToolExecutor tracing."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from tools.builtin.budget import budget_tool
from tools.builtin.weather import weather_tool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from tools.reliability import ToolReliabilityPolicy
from tools.tracing import ToolTracer


@pytest.fixture
def mock_registry() -> Mock:
    tools = {
        "weather": weather_tool._tool_instance,
        "budget": budget_tool._tool_instance,
    }
    registry = Mock(spec=ToolRegistry)

    def _get(name: str):
        if name not in tools:
            raise KeyError(f"Unknown tool: {name}")
        return tools[name]

    registry.get.side_effect = _get
    return registry


@pytest.fixture
def tracer() -> ToolTracer:
    return ToolTracer(session_id="trace-test", debug=False)


@pytest.fixture
def executor(mock_registry: Mock, tracer: ToolTracer) -> ToolExecutor:
    return ToolExecutor(
        mock_registry,
        tracer=tracer,
        reliability=ToolReliabilityPolicy(max_retries=0),
    )


@pytest.mark.asyncio
async def test_trace_record_fields_on_success(executor: ToolExecutor, tracer: ToolTracer) -> None:
    await executor.execute_llm_call({"tool": "weather", "args": {"city": "上海"}})

    assert len(tracer.records) == 1
    record = tracer.records[0]
    assert record.tool_name == "weather"
    assert record.input_args == {"city": "上海"}
    assert record.output is not None
    assert record.output["city"] == "上海"
    assert record.latency_ms >= 0
    assert record.success is True
    assert record.error is None


@pytest.mark.asyncio
async def test_trace_record_fields_on_failure(executor: ToolExecutor, tracer: ToolTracer) -> None:
    await executor.execute_llm_call({"tool": "missing_tool", "args": {}})

    record = tracer.records[0]
    assert record.tool_name == "missing_tool"
    assert record.success is False
    assert record.output is None
    assert record.error is not None
    assert record.latency_ms >= 0


@pytest.mark.asyncio
async def test_export_trace_json(executor: ToolExecutor) -> None:
    await executor.execute_llm_call({"tool": "weather", "args": {"city": "Tokyo"}})
    await executor.execute_llm_call(
        {"tool": "budget", "args": {"days": 2, "currency": "CNY"}},
    )

    log = json.loads(executor.export_trace_json())
    assert log["session_id"] == "trace-test"
    assert log["record_count"] == 2
    assert len(log["records"]) == 2

    first = log["records"][0]
    assert set(first.keys()) == {
        "call_id",
        "tool_name",
        "input_args",
        "output",
        "latency_ms",
        "success",
        "error",
        "parent_id",
        "attempt",
        "max_attempts",
        "is_fallback",
        "original_tool",
        "timestamp",
    }
    assert first["tool_name"] == "weather"
    assert first["success"] is True
    assert isinstance(first["latency_ms"], (int, float))


@pytest.mark.asyncio
async def test_batch_trace_tree_hierarchy(executor: ToolExecutor, tracer: ToolTracer) -> None:
    from schemas.tool import ToolCall

    await executor.execute_batch(
        [
            ToolCall(call_id="c1", name="weather", arguments={"city": "上海"}),
            ToolCall(call_id="c2", name="budget", arguments={"days": 3}),
        ],
    )

    assert len(tracer.records) == 3
    batch = next(r for r in tracer.records if r.tool_name == "__batch__")
    assert batch.parent_id is None
    assert batch.success is True

    children = [r for r in tracer.records if r.parent_id == batch.call_id]
    assert len(children) == 2
    assert [c.tool_name for c in children] == ["weather", "budget"]

    tree = executor.print_trace_tree()
    assert "__batch__" in tree
    assert "weather" in tree
    assert "budget" in tree


@pytest.mark.asyncio
async def test_debug_mode_prints_trace_tree(
    mock_registry: Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    debug_tracer = ToolTracer(session_id="debug-session", debug=True)
    debug_executor = ToolExecutor(mock_registry, tracer=debug_tracer)

    await debug_executor.execute_llm_call({"tool": "weather", "args": {"city": "Beijing"}})

    captured = capsys.readouterr()
    assert "ToolTrace session=debug-session" in captured.out
    assert "weather" in captured.out
    assert "✓" in captured.out
