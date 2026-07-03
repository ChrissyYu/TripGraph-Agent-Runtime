"""Unit tests for execution critic."""

from __future__ import annotations

import json

import pytest

from plan.execution_critic import (
    CRITIC_SYSTEM_PROMPT,
    ExecutionCritic,
    ExecutionCriticConfig,
    RuleBasedExecutionCritic,
    _evaluate_payload,
)
from plan.orchestrator import PlanOrchestrator
from plan.state import PlanState
from schemas.plan import Plan, PlanStep, StepStatus
from agents.planner import PlannerAgent
from core.llm.rule_based import RuleBasedLLMClient
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from tools.reliability import ToolReliabilityPolicy


def _plan() -> Plan:
    return Plan(
        goal="规划上海3日游并计算预算",
        steps=[
            PlanStep(id=1, task="查天气", tool_hint="weather"),
            PlanStep(id=2, task="算预算", tool_hint="budget", dependency=[1]),
        ],
    )


def test_evaluate_payload_success() -> None:
    result = _evaluate_payload(
        {
            "goal": "规划上海3日游并计算预算",
            "tool_outputs": {"weather": {"city": "上海"}, "budget": {"total": 3000}},
            "step_summaries": [
                {"status": "completed"},
                {"status": "completed"},
            ],
            "failed_steps": [],
            "skipped_steps": [],
            "unfinished_steps": [],
        },
    )

    assert result["goal_completed"] is True
    assert result["need_replan"] is False
    assert result["score"] >= 0.85
    assert result["missing_info"] == []


def test_evaluate_payload_missing_budget() -> None:
    result = _evaluate_payload(
        {
            "goal": "规划上海3日游并计算预算",
            "tool_outputs": {"weather": {"city": "上海"}},
            "step_summaries": [{"status": "completed"}, {"status": "failed"}],
            "failed_steps": [2],
            "skipped_steps": [],
            "unfinished_steps": [2],
        },
    )

    assert result["goal_completed"] is False
    assert result["need_replan"] is True
    assert "trip budget" in result["missing_info"]
    assert result["score"] <= 0.6


@pytest.mark.asyncio
async def test_execution_critic_evaluate() -> None:
    state = PlanState.from_plan(_plan())
    state.global_context["tool_outputs"] = {
        "weather": {"city": "上海", "temp_c": 22},
        "budget": {"total": 2500, "currency": "CNY", "days": 3},
    }
    for step in state.plan.steps:
        state.set_step_status(step.id, StepStatus.COMPLETED)

    critic = ExecutionCritic()
    critique = await critic.evaluate(state, "目标：上海3日游\n预算：2500 CNY")

    assert 0.0 <= critique.score <= 1.0
    assert critique.critique
    assert critique.goal_completed is True
    assert critique.need_replan is False


@pytest.mark.asyncio
async def test_rule_based_critic_returns_valid_json() -> None:
    from core.llm.base import LLMMessage

    critic = RuleBasedExecutionCritic()
    raw = await critic.complete(
        [
            LLMMessage(role="system", content=CRITIC_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=json.dumps(
                    {
                        "goal": "规划上海3日游并计算预算",
                        "tool_outputs": {"weather": {}, "budget": {}},
                        "step_summaries": [{"status": "completed"}, {"status": "completed"}],
                        "failed_steps": [],
                        "skipped_steps": [],
                        "unfinished_steps": [],
                    },
                    ensure_ascii=False,
                ),
            ),
        ],
        response_json=True,
    )
    payload = json.loads(raw)
    assert "score" in payload
    assert "critique" in payload
    assert "need_replan" in payload


@pytest.mark.asyncio
async def test_orchestrator_includes_execution_critique() -> None:
    registry = ToolRegistry.default()
    tool_executor = ToolExecutor(
        registry,
        reliability=ToolReliabilityPolicy(max_retries=0),
    )
    planner = PlannerAgent(RuleBasedLLMClient(), tool_registry=registry)
    orchestrator = PlanOrchestrator(planner=planner, tool_executor=tool_executor)

    result = await orchestrator.run("规划上海3日游并计算预算", session_id="critic-test")

    assert result.execution_critique is not None
    assert result.execution_critique.score >= 0.85
    assert result.execution_critique.goal_completed is True
    assert isinstance(result.execution_critique.need_replan, bool)


@pytest.mark.asyncio
async def test_critic_disabled_returns_none_from_orchestrator() -> None:
    registry = ToolRegistry.default()
    tool_executor = ToolExecutor(registry, reliability=ToolReliabilityPolicy(max_retries=0))
    planner = PlannerAgent(RuleBasedLLMClient(), tool_registry=registry)
    critic = ExecutionCritic(
        planner.llm,
        config=ExecutionCriticConfig(enabled=False),
    )
    orchestrator = PlanOrchestrator(
        planner=planner,
        tool_executor=tool_executor,
        execution_critic=critic,
    )

    result = await orchestrator.run("规划上海3日游并计算预算", session_id="no-critic")

    assert result.execution_critique is None
