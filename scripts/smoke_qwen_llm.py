"""Manual smoke test for Qwen LLM integration."""

from __future__ import annotations

import asyncio
import sys
import time
import traceback

from app.bootstrap import bootstrap_runtime
from config.env_loader import bootstrap_environment
from config.settings import Settings, get_settings
from core.llm.fallback_trace import clear_fallback_events
from graph.runtime.execution_policy import ExecutionPolicy
from scripts.smoke_qwen_reporting import build_coverage_lines, build_planner_fallback_lines

QUERY = "帮我规划上海3日游并计算预算"


def _print_friendly_missing_key() -> None:
    print("QWEN_API_KEY is not set.")
    print("To run this smoke test:")
    print("  1. Copy .env.example to .env")
    print("  2. Set LLM_PROVIDER=qwen")
    print("  3. Set EVAL_MODE=auto")
    print("  4. Fill in QWEN_API_KEY=your_qwen_api_key_here")
    print("  5. Run: python scripts/smoke_qwen_llm.py")


def _redact_secrets(text: str, settings: Settings) -> str:
    for secret in (settings.qwen_api_key, settings.openai_api_key):
        if secret:
            text = text.replace(secret, "***REDACTED***")
    return text


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


def _print_replan_history(history) -> None:
    if not history:
        print("\nReplan history: (none)")
        return
    print("\nReplan history:")
    for index, item in enumerate(history, start=1):
        flags = []
        if item.repair_applied:
            flags.append("repair")
        if item.fallback_used:
            flags.append("fallback")
        if item.completed_step_overrides:
            flags.append("completed_override")
        flag_text = f" [{', '.join(flags)}]" if flags else ""
        print(
            f"  #{index} replanned={item.replanned}{flag_text} "
            f"reason={item.replan_reason or item.skipped_reason}",
        )
        if item.repair_notes:
            for note in item.repair_notes:
                print(f"      repair: {note}")
        if item.completed_step_overrides:
            for note in item.completed_step_overrides:
                print(f"      override: {note}")
        if item.validation_errors:
            for err in item.validation_errors:
                print(f"      validation: {err}")


def _print_llm_summary(observability, execution_id: str | None) -> None:
    if not execution_id or not observability.store:
        print("\nLLM call summary: (metrics store unavailable)")
        return
    metrics = observability.store.get(execution_id)
    if metrics is None or not metrics.llm_calls:
        print("\nLLM call summary: (no llm_calls recorded)")
        return
    print("\nLLM call summary:")
    for call in metrics.llm_calls:
        print(
            f"  - caller={call.caller} provider={call.provider} model={call.model} "
            f"latency_ms={round(call.latency_ms, 1)} tokens={call.total_tokens} "
            f"cost_usd={round(call.estimated_cost_usd, 6)}",
        )


async def main() -> int:
    bootstrap_environment()
    settings = get_settings()

    if not settings.qwen_api_key:
        _print_friendly_missing_key()
        return 1

    overrides = settings.model_dump()
    overrides.update(
        {
            "llm_provider": "qwen",
            "eval_mode": "auto",
            "metrics_enabled": True,
            "plan_execution_critic_enabled": True,
        },
    )
    if settings.smoke_max_replan_attempts is not None:
        overrides["plan_critic_max_replan_attempts"] = settings.smoke_max_replan_attempts
    runtime_settings = Settings(**overrides)
    get_settings.cache_clear()

    (
        _registry,
        _memory,
        _manager,
        _tool_executor,
        _orchestrator,
        _router,
        graph_runner,
        _persistence,
        observability,
        _eval,
    ) = bootstrap_runtime(runtime_settings)

    if observability.collector:
        await observability.collector.start()

    print("Provider: qwen")
    print(f"Model (planner): {runtime_settings.qwen_planner_model}")
    print(f"Model (critic): {runtime_settings.qwen_critic_model}")
    print(f"Model (replanner): {runtime_settings.qwen_replanner_model}")
    print(f"QWEN_TIMEOUT_SEC: {runtime_settings.qwen_timeout_sec:g}")
    if runtime_settings.smoke_max_replan_attempts is not None:
        print(f"SMOKE_MAX_REPLAN_ATTEMPTS: {runtime_settings.smoke_max_replan_attempts}")
    print(f"Query: {QUERY}")
    print("-" * 60)

    clear_fallback_events()
    started = time.perf_counter()
    try:
        response = await graph_runner.invoke(
            QUERY,
            session_id="qwen-smoke",
            policy=ExecutionPolicy(capture_state_snapshots=True),
        )
    except Exception as exc:
        print("\nSmoke run failed:")
        print(f"  Error type: {type(exc).__name__}")
        print(f"  Message: {_redact_secrets(str(exc), runtime_settings)}")
        print("\nSuggestions:")
        print("  - Check QWEN_API_KEY and network access to dashscope.aliyuncs.com")
        print("  - Review replan_history / logs for validation or repair fallback")
        print("  - Try PLAN_CRITIC_REPLAN_ENABLED=false to isolate planner-only path")
        traceback.print_exc()
        if observability.collector:
            await observability.collector.stop()
        return 1

    elapsed = time.perf_counter() - started
    if observability.collector:
        await observability.collector.drain()

    print(f"Total latency: {elapsed:.1f}s")

    if response.plan:
        _print_plan_steps(response.plan)
    else:
        print("Plan: (none)")

    repair_notes = (response.state_summary or {}).get("plan_repair_notes")
    if repair_notes:
        print("\nPlan repair notes:")
        for note in repair_notes:
            print(f"  - {note}")

    _print_execution_trace(response.execution_trace)
    _print_replan_history(response.replan_history)

    repair_or_fallback = any(
        item.repair_applied or item.fallback_used for item in (response.replan_history or [])
    )
    recovery_traces = [
        entry
        for entry in (response.execution_trace or [])
        if entry.recovery_action in ("replan_repair", "replan_fallback", "replan_failed")
    ]
    print(f"\nRepair/fallback occurred: {repair_or_fallback or bool(recovery_traces)}")

    final_text = response.final_result or ""
    print("\nPlanner fallback:")
    for line in build_planner_fallback_lines(timeout_sec=runtime_settings.qwen_timeout_sec):
        print(f"  {line}")

    print()
    for line in build_coverage_lines(final_text):
        print(line)

    print("\nFinal result:")
    print(_redact_secrets(final_text or "(empty)", runtime_settings))
    print(f"\nExecution ID: {response.execution_id}")
    if response.execution_id:
        print(
            "Profile endpoint hint: "
            f"GET /api/v1/execution/{response.execution_id}/profile",
        )

    _print_llm_summary(observability, response.execution_id)

    if observability.collector:
        await observability.collector.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
