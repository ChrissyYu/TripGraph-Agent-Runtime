"""Unit tests for critic-driven replanning controller."""

from __future__ import annotations

import pytest

from agents.planner import PlannerAgent
from core.llm.rule_based import RuleBasedLLMClient
from plan.executor import PlanExecutor
from plan.replanning_controller import ReplanningController, ReplanningConfig
from plan.state import PlanState
from plan.validator import PlanValidator
from schemas.execution_critic import ExecutionCritique
from schemas.plan import Plan, PlanStep, StepResult, StepStatus
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from tools.reliability import ToolReliabilityPolicy


def _plan() -> Plan:
    return Plan(
        goal="规划上海3日游并计算预算",
        steps=[
            PlanStep(id=1, task="查询上海天气", tool_hint="weather"),
            PlanStep(id=2, task="计算3天旅行预算", tool_hint="budget", dependency=[1]),
        ],
    )


def _critique(*, need_replan: bool = True) -> ExecutionCritique:
    return ExecutionCritique(
        score=0.4,
        critique="Budget step missing or incomplete",
        need_replan=need_replan,
        goal_completed=False,
        missing_info=["trip budget"],
    )


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry.default()


@pytest.mark.asyncio
async def test_no_replan_when_critique_does_not_require_it(registry: ToolRegistry) -> None:
    state = PlanState.from_plan(_plan())
    planner = PlannerAgent(RuleBasedLLMClient(), tool_registry=registry)
    controller = ReplanningController(planner, PlanValidator(registry))

    outcome = await controller.handle(
        _critique(need_replan=False),
        state,
    )

    assert outcome.result.replanned is False
    assert outcome.result.skipped_reason == "critic_need_replan=false"
    assert len(state.execution_trace) == 0


@pytest.mark.asyncio
async def test_replan_preserves_completed_steps(registry: ToolRegistry) -> None:
    state = PlanState.from_plan(_plan())
    state.set_step_status(1, StepStatus.COMPLETED)
    state.record_step_result(
        StepResult(
            step_id=1,
            task="查询上海天气",
            status=StepStatus.COMPLETED,
            tool_name="weather",
            observation={"city": "上海", "temp_c": 22},
        ),
    )
    state.set_step_status(2, StepStatus.FAILED)

    planner = PlannerAgent(RuleBasedLLMClient(), tool_registry=registry)
    controller = ReplanningController(
        planner,
        PlanValidator(registry),
        config=ReplanningConfig(max_replan_attempts=2),
    )

    outcome = await controller.handle(_critique(), state)

    assert outcome.result.replanned is True
    assert outcome.result.replan_reason
    assert outcome.result.new_plan.steps[0].id == 1
    assert outcome.result.new_plan.steps[0].task == "查询上海天气"
    assert state.get_step_status(1) == StepStatus.COMPLETED
    assert len(state.plan.steps) >= 2
    assert any(s.tool_hint == "budget" for s in state.plan.steps[1:])

    critic_traces = [t for t in state.execution_trace if t.recovery_action == "critic_replan"]
    assert len(critic_traces) == 1
    assert critic_traces[0].error == outcome.result.replan_reason


@pytest.mark.asyncio
async def test_max_replan_attempts_enforced(registry: ToolRegistry) -> None:
    state = PlanState.from_plan(_plan())
    planner = PlannerAgent(RuleBasedLLMClient(), tool_registry=registry)
    controller = ReplanningController(
        planner,
        PlanValidator(registry),
        config=ReplanningConfig(max_replan_attempts=1),
    )

    first = await controller.handle(_critique(), state)
    assert first.result.replanned is True

    second = await controller.handle(_critique(), state)
    assert second.result.replanned is False
    assert second.result.skipped_reason == "max_replan_attempts=1"


@pytest.mark.asyncio
async def test_orchestrator_replan_loop(registry: ToolRegistry) -> None:
    from plan.orchestrator import PlanOrchestrator
    from plan.execution_critic import ExecutionCritic

    class FirstPassReplanCritic(ExecutionCritic):
        def __init__(self) -> None:
            super().__init__(llm=None)
            self._calls = 0

        async def evaluate(self, state: PlanState, final_result: str) -> ExecutionCritique:
            self._calls += 1
            if self._calls == 1:
                return _critique(need_replan=True)
            return ExecutionCritique(
                score=0.95,
                critique="All required outputs present",
                need_replan=False,
                goal_completed=True,
                missing_info=[],
            )

    tool_executor = ToolExecutor(registry, reliability=ToolReliabilityPolicy(max_retries=0))
    planner = PlannerAgent(RuleBasedLLMClient(), tool_registry=registry)
    orchestrator = PlanOrchestrator(
        planner=planner,
        tool_executor=tool_executor,
        execution_critic=FirstPassReplanCritic(),
    )

    result = await orchestrator.run("规划上海3日游并计算预算", session_id="replan-loop")

    assert result.replan_history
    assert result.replan_history[0].replanned is True
    assert any(t.recovery_action == "critic_replan" for t in result.execution_trace)
    assert result.execution_critique is not None
    assert result.execution_critique.need_replan is False
