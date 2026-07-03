"""Unit tests for plan context compression."""

from __future__ import annotations

import json
from typing import Any

import pytest

from plan.context_compression import (
    ContextCompressionConfig,
    ContextCompressor,
    RuleBasedContextSummarizer,
)
from plan.executor import PlanExecutor
from plan.state import PlanState
from schemas.plan import Plan, PlanStep, StepResult, StepStatus
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from tools.reliability import ToolReliabilityPolicy


def _plan() -> Plan:
    return Plan(
        goal="上海3日游",
        steps=[
            PlanStep(id=1, task="查天气", tool_hint="weather"),
            PlanStep(id=2, task="算预算", tool_hint="budget", dependency=[1]),
        ],
    )


def _fat_context(base: dict[str, Any] | None = None) -> dict[str, Any]:
    context = {
        "city": "上海",
        "days": 3,
        "user_query": "规划上海3日游",
        "tool_outputs": {
            "weather": {"city": "上海", "temp_c": 22, "condition": "sunny"},
        },
        "step_outputs": {
            1: {"city": "上海", "temp_c": 22, "condition": "sunny", "notes": "x" * 500},
        },
        "verbose_history": "y" * 3000,
        "scratch": {"detail": "z" * 1500},
    }
    if base:
        context.update(base)
    return context


def test_should_compress_when_over_threshold() -> None:
    compressor = ContextCompressor(
        config=ContextCompressionConfig(enabled=True, max_chars=500),
    )
    assert compressor.should_compress(_fat_context()) is True
    assert compressor.should_compress({"city": "上海"}) is False


def test_should_not_compress_when_disabled() -> None:
    compressor = ContextCompressor(
        config=ContextCompressionConfig(enabled=False, max_chars=10),
    )
    assert compressor.should_compress(_fat_context()) is False


@pytest.mark.asyncio
async def test_compress_produces_summary_and_replaces_context() -> None:
    state = PlanState.from_plan(_plan())
    state.global_context = _fat_context()
    state.set_step_status(1, StepStatus.COMPLETED)
    state.current_step = 2

    compressor = ContextCompressor(
        config=ContextCompressionConfig(enabled=True, max_chars=500),
    )
    result = await compressor.compress(state)

    assert result.compressed_context
    assert result.key_facts
    assert "verbose_history" not in state.global_context
    assert "scratch" not in state.global_context
    assert "step_outputs" in state.global_context
    assert state.global_context["compressed_context"] == result.compressed_context
    assert state.global_context["key_facts"] == result.key_facts
    assert state.global_context["tool_outputs"]["weather"]["city"] == "上海"
    assert state.global_context["city"] == "上海"
    assert state.global_context["_compression_meta"]["compression_count"] == 1
    assert state.get_step_status(1) == StepStatus.COMPLETED


@pytest.mark.asyncio
async def test_rule_based_summarizer_returns_json() -> None:
    from core.llm.base import LLMMessage

    from plan.context_compression import COMPRESSION_SYSTEM_PROMPT

    summarizer = RuleBasedContextSummarizer()
    raw = await summarizer.complete(
        [
            LLMMessage(role="system", content=COMPRESSION_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=json.dumps(
                    {
                        "goal": "上海3日游",
                        "tool_outputs": {"weather": {"city": "上海", "temp_c": 20}},
                        "step_outputs": {1: {"city": "上海"}},
                        "misc": {},
                    },
                    ensure_ascii=False,
                ),
            ),
        ],
        response_json=True,
    )
    payload = json.loads(raw)
    assert payload["compressed_context"]
    assert payload["key_facts"]


@pytest.mark.asyncio
async def test_plan_executor_triggers_compression_after_step() -> None:
    registry = ToolRegistry.default()
    tool_executor = ToolExecutor(
        registry,
        reliability=ToolReliabilityPolicy(max_retries=0),
    )
    plan_executor = PlanExecutor(
        tool_executor,
        context_compression=ContextCompressionConfig(enabled=True, max_chars=200),
    )

    state = PlanState.from_plan(_plan())
    state.global_context.update(
        {
            "city": "上海",
            "days": 3,
            "origin": "A",
            "destination": "B",
            "padding": "p" * 500,
        },
    )

    await plan_executor.execute(state.plan, state)

    assert state.global_context.get("compressed_context")
    assert state.global_context.get("key_facts")
    assert state.global_context["tool_outputs"]
    assert state.summary()["compression_count"] >= 1
    assert all(state.get_step_status(s.id) == StepStatus.COMPLETED for s in state.plan.steps)
