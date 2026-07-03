"""Manual smoke test for MCP tool integration (Phase 9B)."""

from __future__ import annotations

import asyncio
import json
import sys
import time

from app.bootstrap import bootstrap_runtime
from config.env_loader import bootstrap_environment
from config.settings import Settings, get_settings
from graph.runtime.execution_policy import ExecutionPolicy
from plan.final_synthesis import check_final_result_coverage
from tools.mcp.bootstrap import shutdown_mcp_client, wire_mcp_tools
from tools.registry import ToolRegistry

QUERY = "使用 MCP 工具帮我规划上海3日游并计算预算"


def _print_plan_steps(plan) -> None:
    print("Plan steps:")
    for step in plan.steps:
        deps = step.dependency or []
        print(
            f"  [{step.id}] {step.task} "
            f"(tool_hint={step.tool_hint}, dependencies={deps})",
        )


def _print_execution_trace(trace) -> None:
    if not trace:
        print("\nExecution trace: (empty)")
        return
    print("\nExecution trace:")
    for entry in trace:
        if entry.tool_name:
            status = "ok" if entry.success else (entry.error or "failed")
            print(f"  - step {entry.step_id} | {entry.tool_name}: {status}")
        elif entry.recovery_action:
            print(
                f"  - step {entry.step_id} | {entry.recovery_action}: "
                f"{entry.error or entry.task}",
            )


def _print_mcp_tool_calls(tool_trace_json: str) -> None:
    print("\nMCP tool calls (from tracer):")
    if not tool_trace_json or tool_trace_json == "[]":
        print("  (none)")
        return
    import json

    payload = json.loads(tool_trace_json)
    if isinstance(payload, dict) and "records" in payload:
        records = payload["records"]
    elif isinstance(payload, list):
        records = payload
    else:
        records = []
    mcp_records = [item for item in records if str(item.get("tool_name", "")).startswith("mcp_")]
    if not mcp_records:
        print("  (no mcp_* tool calls recorded)")
        return
    for item in mcp_records:
        print(
            f"  - {item.get('tool_name')} success={item.get('success')} "
            f"latency_ms={round(item.get('latency_ms', 0), 1)}",
        )


async def main() -> int:
    bootstrap_environment()
    settings = get_settings()

    overrides = settings.model_dump()
    overrides.update(
        {
            "mcp_enabled": True,
            "llm_provider": "rule_based",
            "eval_mode": "deterministic_eval",
            "metrics_enabled": True,
            "plan_execution_critic_enabled": False,
            "plan_critic_replan_enabled": False,
        },
    )
    runtime_settings = Settings(**overrides)
    get_settings.cache_clear()

    print("MCP smoke: Phase 9B")
    print(f"MCP_ENABLED: {runtime_settings.mcp_enabled}")
    print(f"LLM mode: {runtime_settings.eval_mode} / {runtime_settings.llm_provider}")
    print(f"MCP server: {runtime_settings.mcp_server_command} {' '.join(runtime_settings.mcp_server_args)}")
    print(f"Query: {QUERY}")
    print("-" * 60)

    tool_registry = ToolRegistry.default()
    await wire_mcp_tools(tool_registry, runtime_settings)

    (
        tool_registry,
        _memory,
        _manager,
        _tool_executor,
        _orchestrator,
        _router,
        graph_runner,
        _persistence,
        observability,
        _eval,
    ) = bootstrap_runtime(runtime_settings, tool_registry=tool_registry, mcp_wire=False)

    mcp_tools = sorted(name for name in tool_registry.list_names() if name.startswith("mcp_"))
    print("Registered MCP tools:", mcp_tools or "(none)")
    if not mcp_tools:
        print("ERROR: MCP tools were not registered. Check MCP server startup.")
        await shutdown_mcp_client()
        return 1

    if observability.collector:
        await observability.collector.start()

    started = time.perf_counter()
    try:
        response = await graph_runner.invoke(
            QUERY,
            session_id="mcp-smoke",
            policy=ExecutionPolicy(capture_state_snapshots=True),
        )
    except Exception as exc:
        print(f"\nSmoke run failed: {type(exc).__name__}: {exc}")
        if observability.collector:
            await observability.collector.stop()
        await shutdown_mcp_client()
        return 1

    elapsed = time.perf_counter() - started
    if observability.collector:
        await observability.collector.drain()

    print(f"Total latency: {elapsed:.1f}s")
    if response.plan:
        _print_plan_steps(response.plan)
    _print_execution_trace(response.execution_trace)
    _print_mcp_tool_calls(_tool_executor.export_trace_json())

    final_text = response.final_result or ""
    coverage = check_final_result_coverage(final_text)
    print("\nFinal result coverage:")
    for key, value in coverage.items():
        print(f"  {key}: {value}")

    print("\nFinal result:")
    print(final_text or "(empty)")
    print(f"\nExecution ID: {response.execution_id}")

    await shutdown_mcp_client()
    if observability.collector:
        await observability.collector.stop()

    trace_payload = json.loads(_tool_executor.export_trace_json())
    trace_records = trace_payload.get("records", []) if isinstance(trace_payload, dict) else []
    mcp_in_tracer = any(
        str(item.get("tool_name", "")).startswith("mcp_") for item in trace_records
    )
    mcp_in_execution = any(
        entry.tool_name and entry.tool_name.startswith("mcp_")
        for entry in (response.execution_trace or [])
    )
    if not (mcp_in_tracer or mcp_in_execution):
        print("\nWARNING: no mcp_* tool calls recorded in tracer or execution_trace.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
