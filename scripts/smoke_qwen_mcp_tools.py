"""Manual smoke: Qwen planner + MCP tools + tool policy (Phase 9C)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

from app.bootstrap import bootstrap_runtime
from config.env_loader import bootstrap_environment
from config.settings import Settings, get_settings
from graph.runtime.execution_policy import ExecutionPolicy
from plan.final_synthesis import check_final_result_coverage
from tools.mcp.bootstrap import shutdown_mcp_client, wire_mcp_tools

QUERY = "使用 MCP 工具帮我规划上海3日游并计算预算"


def _print_plan_steps(plan) -> None:
    print("Plan steps:")
    for step in plan.steps:
        deps = step.dependency or []
        print(
            f"  [{step.id}] {step.task} "
            f"(tool_hint={step.tool_hint}, dependencies={deps})",
        )


def _print_policy_trace(observations: dict) -> None:
    trace = observations.get("tool_policy_trace") or []
    print("\nTool policy trace:")
    if not trace:
        print("  (empty)")
        return
    for entry in trace:
        print(
            f"  - step {entry.get('step_id')} | "
            f"hint={entry.get('original_tool_hint')} → selected={entry.get('selected_tool')} "
            f"provider={entry.get('selected_provider')} policy={entry.get('policy_name')} "
            f"fallback_used={entry.get('fallback_used')}",
        )
    counters = observations.get("tool_policy_counters")
    if counters:
        print("  counters:", counters)


def _print_execution_trace(trace) -> None:
    if not trace:
        print("\nExecution trace: (empty)")
        return
    print("\nExecution trace:")
    for entry in trace:
        if entry.tool_name:
            status = "ok" if entry.success else (entry.error or "failed")
            extra = f" recovery={entry.recovery_action}" if entry.recovery_action else ""
            print(f"  - step {entry.step_id} | {entry.tool_name}: {status}{extra}")
        elif entry.recovery_action:
            print(
                f"  - step {entry.step_id} | {entry.recovery_action}: "
                f"{entry.error or entry.task}",
            )


async def main() -> int:
    bootstrap_environment()
    settings = get_settings()

    if not settings.qwen_api_key and not os.environ.get("QWEN_API_KEY"):
        print("QWEN_API_KEY is not set.")
        print("Export QWEN_API_KEY to run this manual smoke test.")
        return 0

    overrides = settings.model_dump()
    overrides.update(
        {
            "mcp_enabled": True,
            "llm_provider": "qwen",
            "eval_mode": "real_llm_eval",
            "tool_policy_enabled": True,
            "tool_policy_strategy": "mcp_first",
            "tool_policy_mcp_fallback_enabled": True,
            "metrics_enabled": True,
            "plan_execution_critic_enabled": False,
            "plan_critic_replan_enabled": False,
        },
    )
    runtime_settings = Settings(**overrides)
    get_settings.cache_clear()

    print("Qwen + MCP smoke: Phase 9C")
    print(f"Provider/model: qwen / {runtime_settings.qwen_planner_model}")
    print(f"MCP_ENABLED: {runtime_settings.mcp_enabled}")
    print(f"TOOL_POLICY_STRATEGY: {runtime_settings.tool_policy_strategy}")
    print(f"Query: {QUERY}")
    print("-" * 60)

    tool_registry = __import__("tools.registry", fromlist=["ToolRegistry"]).ToolRegistry.default()
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

    all_tools = tool_registry.list_names()
    builtin_tools = [n for n in all_tools if not n.startswith("mcp_")]
    mcp_tools = [n for n in all_tools if n.startswith("mcp_")]
    print("Registered builtin tools:", builtin_tools)
    print("Registered MCP tools:", mcp_tools or "(none)")

    if observability.collector:
        await observability.collector.start()

    started = time.perf_counter()
    try:
        response = await graph_runner.invoke(
            QUERY,
            session_id="qwen-mcp-smoke",
            policy=ExecutionPolicy(capture_state_snapshots=True),
        )
    except Exception as exc:
        print(f"\nSmoke run failed: {type(exc).__name__}: {exc}")
        await shutdown_mcp_client()
        if observability.collector:
            await observability.collector.stop()
        return 1

    elapsed = time.perf_counter() - started
    if observability.collector:
        await observability.collector.drain()

    print(f"Total latency: {elapsed:.1f}s")
    if response.plan:
        _print_plan_steps(response.plan)

    state_summary = response.state_summary or {}
    _print_policy_trace(state_summary)
    _print_execution_trace(response.execution_trace)

    fallback_used = any(
        entry.get("fallback_used") for entry in (state_summary.get("tool_policy_trace") or [])
    )
    print(f"\nfallback_used (policy trace): {fallback_used}")

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
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
