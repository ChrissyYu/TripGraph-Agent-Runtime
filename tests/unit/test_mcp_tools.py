"""Phase 9B: MCP tool integration tests (no external APIs)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from app.bootstrap import bootstrap_runtime
from config.settings import Settings, get_settings
from tools.adapters.mcp import MCPToolAdapter, MCPToolProvider
from tools.executor import ToolExecutor
from tools.mcp.bootstrap import wire_mcp_tools
from tools.registry import ToolRegistry
from tools.reliability import ToolReliabilityPolicy
from tools.tracing import ToolTracer


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_PATH = REPO_ROOT / "mcp_servers" / "trip_tools_server.py"


class FakeMCPClient:
    """In-memory MCP client for adapter/registry unit tests."""

    async def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "mcp_weather",
                "description": "MCP weather",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}, "date": {"type": "string"}},
                    "required": ["city"],
                },
            },
            {
                "name": "mcp_map",
                "description": "MCP map",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "destination": {"type": "string"},
                        "origin": {"type": "string"},
                        "day": {"type": "integer"},
                    },
                    "required": ["destination"],
                },
            },
            {
                "name": "mcp_budget",
                "description": "MCP budget",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"},
                        "days": {"type": "integer"},
                        "currency": {"type": "string"},
                    },
                    "required": ["city", "days"],
                },
            },
            {
                "name": "other_tool",
                "description": "Should be filtered by prefix",
                "input_schema": {"type": "object", "properties": {}},
            },
        ]

    async def call_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "mcp_weather":
            return {
                "city": args.get("city", "上海"),
                "date": args.get("date", "today"),
                "condition": "sunny",
                "temp_c": 22,
                "source": "mcp_mock",
            }
        if tool_name == "mcp_map":
            return {
                "route": f"{args.get('origin', '酒店')} → {args.get('destination', '外滩')}",
                "duration_min": 42,
                "places": [args.get("destination", "外滩")],
                "source": "mcp_mock",
            }
        if tool_name == "mcp_budget":
            return {
                "total": 2100.0,
                "currency": args.get("currency", "CNY"),
                "days": args.get("days", 3),
                "breakdown": {"food": 600.0},
                "source": "mcp_mock",
            }
        raise KeyError(tool_name)


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_mcp_server_exposes_trip_tools() -> None:
    assert SERVER_PATH.is_file()
    source = SERVER_PATH.read_text(encoding="utf-8")
    for name in ("mcp_weather", "mcp_map", "mcp_budget"):
        assert f'name="{name}"' in source or f"def {name}" in source


@pytest.mark.asyncio
async def test_mcp_adapter_discovers_tools() -> None:
    provider = MCPToolProvider(FakeMCPClient(), tool_prefix="mcp_")
    adapters = await provider.list_tools()
    names = [adapter.name for adapter in adapters]
    assert names == ["mcp_weather", "mcp_map", "mcp_budget"]


@pytest.mark.asyncio
async def test_mcp_tool_converted_to_base_tool() -> None:
    provider = MCPToolProvider(FakeMCPClient(), tool_prefix="mcp_")
    adapter = (await provider.list_tools())[0]
    base_tool = adapter.to_base_tool()
    assert base_tool.name == "mcp_weather"
    result = await base_tool.run({"city": "上海", "date": "today"})
    assert result["source"] == "mcp_mock"
    assert result["city"] == "上海"


@pytest.mark.asyncio
async def test_mcp_tool_registered_in_tool_registry() -> None:
    registry = ToolRegistry()
    provider = MCPToolProvider(FakeMCPClient(), tool_prefix="mcp_")
    count = await provider.register_all(registry)
    assert count == 3
    assert registry.has("mcp_weather")
    assert registry.has("mcp_map")
    assert registry.has("mcp_budget")


@pytest.mark.asyncio
async def test_tool_executor_can_call_mcp_weather() -> None:
    registry = ToolRegistry()
    provider = MCPToolProvider(FakeMCPClient(), tool_prefix="mcp_")
    await provider.register_all(registry)
    executor = ToolExecutor(registry, reliability=ToolReliabilityPolicy(max_retries=0))
    result = await executor.execute_llm_call({"tool": "mcp_weather", "args": {"city": "上海"}})
    assert result.success is True
    assert result.output["source"] == "mcp_mock"


@pytest.mark.asyncio
async def test_mcp_tool_trace_recorded() -> None:
    registry = ToolRegistry()
    provider = MCPToolProvider(FakeMCPClient(), tool_prefix="mcp_")
    await provider.register_all(registry)
    records: list[dict[str, Any]] = []
    tracer = ToolTracer(on_record=lambda entry: records.append(entry.to_log_dict()))
    executor = ToolExecutor(
        registry,
        tracer=tracer,
        reliability=ToolReliabilityPolicy(max_retries=0),
    )
    await executor.execute_llm_call({"tool": "mcp_map", "args": {"destination": "外滩"}})
    assert records
    assert records[0]["tool_name"] == "mcp_map"
    assert records[0]["success"] is True


def test_mcp_disabled_does_not_affect_builtin_tools(monkeypatch) -> None:
    monkeypatch.setenv("MCP_ENABLED", "false")
    get_settings.cache_clear()
    settings = Settings(mcp_enabled=False)
    registry = ToolRegistry.default()
    names = registry.list_names()
    assert "weather" in names
    assert "map" in names
    assert "budget" in names
    assert not any(name.startswith("mcp_") for name in names)
    _registry, *_rest = bootstrap_runtime(settings)
    assert "weather" in _registry.list_names()
    assert not any(name.startswith("mcp_") for name in _registry.list_names())


@pytest.mark.asyncio
async def test_bootstrap_with_mcp_enabled_registers_mcp_tools_mocked(monkeypatch) -> None:
    monkeypatch.setenv("MCP_ENABLED", "true")
    get_settings.cache_clear()
    registry = ToolRegistry.default()
    settings = Settings(mcp_enabled=True, mcp_required=False)
    client = FakeMCPClient()
    await wire_mcp_tools(registry, settings, client=client)
    assert registry.has("mcp_weather")
    assert registry.has("mcp_map")
    assert registry.has("mcp_budget")
    assert registry.has("weather")


@pytest.mark.asyncio
async def test_smoke_mcp_does_not_require_real_external_api() -> None:
    """Smoke script path uses RuleBased + mocked graph runner (no DashScope / no HTTP weather API)."""
    from unittest.mock import patch

    from scripts import smoke_mcp_tools
    from tools.mcp import bootstrap as mcp_bootstrap

    mcp_bootstrap._active_client = None
    fake_client = FakeMCPClient()

    from schemas.plan import ExecutionTraceEntry, Plan, PlanStep, StepStatus

    registry = ToolRegistry.default()
    await wire_mcp_tools(registry, Settings(mcp_enabled=True), client=fake_client)

    class _Runner:
        async def invoke(self, query, **kwargs):
            from schemas.graph_runtime import GraphExecuteResponse

            return GraphExecuteResponse(
                session_id="mcp-smoke",
                plan=Plan(
                    goal=query,
                    steps=[
                        PlanStep(id=1, task="查天气", tool_hint="mcp_weather"),
                        PlanStep(id=2, task="路线", tool_hint="mcp_map", dependency=[1]),
                        PlanStep(id=3, task="预算", tool_hint="mcp_budget", dependency=[2]),
                    ],
                ),
                graph_trace=[],
                execution_trace=[
                    ExecutionTraceEntry(
                        step_id=1,
                        task="查天气",
                        status=StepStatus.COMPLETED,
                        tool_name="mcp_weather",
                        success=True,
                    ),
                ],
                node_timeline=[],
                final_result="目标：x\n天气信息：\n- 上海\n行程路线：\n- 酒店 → 外滩\n预算估算：\n- 2100 CNY",
                state_summary={},
                execution_id="exec-mcp-test",
            )

    with patch.object(smoke_mcp_tools, "bootstrap_runtime") as bootstrap_mock:
        bootstrap_mock.return_value = (
            registry,
            None,
            None,
            ToolExecutor(registry),
            None,
            None,
            _Runner(),
            None,
            type("Obs", (), {"collector": None})(),
            None,
        )
        exit_code = await smoke_mcp_tools.main()
        assert exit_code == 0


@pytest.mark.asyncio
async def test_mcp_stdio_server_roundtrip() -> None:
    pytest.importorskip("mcp")
    from tools.mcp.client import MCPStdioClient

    client = MCPStdioClient(command=sys.executable, args=[str(SERVER_PATH)])
    try:
        tools = await client.list_tools()
        names = [item["name"] for item in tools]
        assert "mcp_weather" in names
        result = await client.call_tool("mcp_weather", {"city": "上海"})
        assert result["source"] == "mcp_mock"
        assert result["city"] == "上海"
    finally:
        await client.disconnect()
