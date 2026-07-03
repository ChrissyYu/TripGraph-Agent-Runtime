"""Unit tests for ToolExecutor with mocked ToolRegistry."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import Mock

import pytest

from schemas.tool import LLMExecutionResult, LLMOutputKind, ToolObservation
from tools.builtin.budget import budget_tool
from tools.builtin.map import map_tool
from tools.builtin.weather import weather_tool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from tools.reliability import ToolReliabilityPolicy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WEATHER_OUTPUT_KEYS = {"city", "date", "temp_c", "condition", "humidity_pct", "source"}
MAP_OUTPUT_KEYS = {"origin", "destination", "mode", "distance_km", "duration_min", "steps", "source"}
BUDGET_OUTPUT_KEYS = {"days", "currency", "breakdown", "daily_total", "total"}


def assert_observation_structure(
    obs: ToolObservation,
    *,
    tool: str,
    success: bool,
    args: dict[str, Any] | None = None,
    output_keys: set[str] | None = None,
    error_contains: str | None = None,
) -> None:
    assert isinstance(obs, ToolObservation)
    assert obs.tool == tool
    assert obs.success is success
    assert isinstance(obs.args, dict)

    if args is not None:
        assert obs.args == args

    if success:
        assert obs.error is None
        assert obs.output is not None
        if output_keys is not None:
            assert isinstance(obs.output, dict)
            assert output_keys <= obs.output.keys()
    else:
        assert obs.output is None
        assert obs.error is not None
        if error_contains is not None:
            assert error_contains.lower() in obs.error.lower()


def assert_execution_result_structure(
    result: LLMExecutionResult,
    *,
    kind: LLMOutputKind,
    final: str | None = None,
    error_contains: str | None = None,
) -> None:
    assert isinstance(result, LLMExecutionResult)
    assert result.kind == kind

    if kind == LLMOutputKind.TOOL_CALL:
        assert result.observation is not None
        assert result.final is None
        assert result.error is None
    elif kind == LLMOutputKind.FINAL:
        assert result.observation is None
        assert result.final == final
        assert result.error is None
    elif kind == LLMOutputKind.PARSE_ERROR:
        assert result.observation is None
        assert result.final is None
        assert result.error is not None
        if error_contains is not None:
            assert error_contains.lower() in result.error.lower()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_registry() -> Mock:
    """Mock ToolRegistry backed by real builtin tool instances."""
    tools = {
        "weather": weather_tool._tool_instance,
        "map": map_tool._tool_instance,
        "budget": budget_tool._tool_instance,
    }

    registry = Mock(spec=ToolRegistry)
    registry.list_names.return_value = sorted(tools.keys())

    def _get(name: str):
        if name not in tools:
            raise KeyError(f"Unknown tool: {name}. Available: {', '.join(tools)}")
        return tools[name]

    registry.get.side_effect = _get
    registry.has.side_effect = lambda name: name in tools
    return registry


@pytest.fixture
def executor(mock_registry: Mock) -> ToolExecutor:
    return ToolExecutor(
        mock_registry,
        reliability=ToolReliabilityPolicy(max_retries=0),
    )


# ---------------------------------------------------------------------------
# 1. Normal tool calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "tool", "args", "output_keys", "output_assertions"),
    [
        pytest.param(
            {"tool": "weather", "args": {"city": "Shanghai", "date": "today"}},
            "weather",
            {"city": "Shanghai", "date": "today"},
            WEATHER_OUTPUT_KEYS,
            lambda out: out["city"] == "Shanghai" and isinstance(out["temp_c"], int),
            id="weather",
        ),
        pytest.param(
            {"tool": "map", "args": {"origin": "Beijing", "destination": "Shanghai"}},
            "map",
            {"origin": "Beijing", "destination": "Shanghai"},
            MAP_OUTPUT_KEYS,
            lambda out: out["distance_km"] > 0 and len(out["steps"]) >= 3,
            id="map",
        ),
        pytest.param(
            {"tool": "budget", "args": {"days": 5, "daily_food": 150.0, "currency": "CNY"}},
            "budget",
            {"days": 5, "daily_food": 150.0, "currency": "CNY"},
            BUDGET_OUTPUT_KEYS,
            lambda out: out["days"] == 5 and out["total"] > 0,
            id="budget",
        ),
    ],
)
async def test_normal_tool_call(
    executor: ToolExecutor,
    payload: dict,
    tool: str,
    args: dict,
    output_keys: set[str],
    output_assertions,
) -> None:
    obs = await executor.execute_llm_call(payload)

    assert_observation_structure(
        obs,
        tool=tool,
        success=True,
        args=args,
        output_keys=output_keys,
    )
    assert output_assertions(obs.output)


# ---------------------------------------------------------------------------
# 2. Tool not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_not_found(executor: ToolExecutor, mock_registry: Mock) -> None:
    obs = await executor.execute_llm_call({"tool": "flight_search", "args": {"from": "PEK"}})

    assert_observation_structure(
        obs,
        tool="flight_search",
        success=False,
        args={"from": "PEK"},
        error_contains="unknown tool",
    )
    mock_registry.get.assert_called_once_with("flight_search")


# ---------------------------------------------------------------------------
# 3. Missing required args
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "args", "missing_field"),
    [
        pytest.param("weather", {}, "city", id="weather_missing_city"),
        pytest.param("map", {"origin": "A"}, "destination", id="map_missing_destination"),
        pytest.param("budget", {"daily_food": 100}, "days", id="budget_missing_days"),
    ],
)
async def test_missing_required_args(
    executor: ToolExecutor,
    tool: str,
    args: dict,
    missing_field: str,
) -> None:
    obs = await executor.execute_llm_call({"tool": tool, "args": args})

    assert_observation_structure(
        obs,
        tool=tool,
        success=False,
        args=args,
        error_contains=missing_field,
    )


# ---------------------------------------------------------------------------
# 4. Wrong arg types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "args", "field"),
    [
        pytest.param("weather", {"city": ["Shanghai"]}, "city", id="weather_city_not_string"),
        pytest.param("budget", {"days": "three"}, "days", id="budget_days_not_int"),
        pytest.param("budget", {"days": 3, "daily_food": "expensive"}, "daily_food", id="budget_food_not_float"),
    ],
)
async def test_invalid_arg_types(
    executor: ToolExecutor,
    tool: str,
    args: dict,
    field: str,
) -> None:
    obs = await executor.execute_llm_call({"tool": tool, "args": args})

    assert_observation_structure(
        obs,
        tool=tool,
        success=False,
        args=args,
        error_contains=field,
    )


# ---------------------------------------------------------------------------
# 5. Invalid JSON from LLM
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param('{"tool": "weather", "args": {broken}', id="broken_json_object"),
        pytest.param("[not", id="broken_json_array"),
        pytest.param('{"unexpected": true}', id="json_without_tool_or_final"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_llm_json(executor: ToolExecutor, raw: str) -> None:
    result = await executor.process_llm_output(raw)

    assert_execution_result_structure(result, kind=LLMOutputKind.PARSE_ERROR)
    assert result.observation is None
    assert result.final is None


# ---------------------------------------------------------------------------
# 6. Non-tool-call final response
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("Your 3-day Tokyo itinerary is ready.", id="plain_text_final"),
        pytest.param('{"final": "Budget summary: total 4500 CNY."}', id="json_final_field"),
        pytest.param('{"content": "Route confirmed via map tool."}', id="json_content_field"),
    ],
)
@pytest.mark.asyncio
async def test_llm_final_response_without_tool_call(
    executor: ToolExecutor,
    mock_registry: Mock,
    raw: str,
) -> None:
    result = await executor.process_llm_output(raw)

    expected_final = raw if not raw.startswith("{") else json.loads(raw)
    if isinstance(expected_final, dict):
        expected_final = expected_final.get("final") or expected_final.get("content")

    assert_execution_result_structure(
        result,
        kind=LLMOutputKind.FINAL,
        final=expected_final,
    )
    assert result.observation is None
    mock_registry.get.assert_not_called()


@pytest.mark.asyncio
async def test_process_llm_output_tool_call_delegates_to_executor(executor: ToolExecutor) -> None:
    result = await executor.process_llm_output(
        {"tool": "weather", "args": {"city": "Tokyo"}},
    )

    assert_execution_result_structure(result, kind=LLMOutputKind.TOOL_CALL)
    assert result.observation is not None
    assert_observation_structure(
        result.observation,
        tool="weather",
        success=True,
        args={"city": "Tokyo"},
        output_keys=WEATHER_OUTPUT_KEYS,
    )
