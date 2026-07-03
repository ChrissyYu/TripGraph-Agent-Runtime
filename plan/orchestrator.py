"""Plan-driven orchestration: User → Planner → Executor → Final."""

from __future__ import annotations

from typing import Any, Protocol

from agents.planner import PlannerAgent
from core.exceptions import PlanValidationError
from core.logging import get_logger
from plan.execution_critic import ExecutionCritic, ExecutionCriticConfig
from plan.executor import PlanExecutor
from plan.replanning_controller import ReplanningController, ReplanningConfig
from plan.resolver import StepToolResolver
from plan.state import PlanState
from plan.validator import PlanValidator
from plan.final_synthesis import synthesize_final_result
from schemas.plan import ExecutionTraceEntry, Plan, PlanExecuteResponse, StepStatus
from schemas.replanning import ReplanningResult
from tools.executor import ToolExecutor

logger = get_logger(__name__)


class PlanGraphHook(Protocol):
    """Future LangGraph integration point."""

    async def on_plan_created(self, plan: Plan, state: PlanState) -> None: ...

    async def on_step_completed(self, state: PlanState) -> None: ...

    async def on_plan_finished(self, state: PlanState, final_result: str) -> None: ...


class PlanOrchestrator:
    """Full plan-driven loop coordinating planner, executor, and synthesis."""

    def __init__(
        self,
        planner: PlannerAgent,
        tool_executor: ToolExecutor,
        *,
        plan_executor: PlanExecutor | None = None,
        resolver: StepToolResolver | None = None,
        validator: PlanValidator | None = None,
        graph_hook: PlanGraphHook | None = None,
        execution_critic: ExecutionCritic | None = None,
        replanning_controller: ReplanningController | None = None,
    ) -> None:
        self._planner = planner
        self._tool_executor = tool_executor
        self._resolver = resolver or StepToolResolver()
        self._validator = validator or PlanValidator(tool_executor.registry)
        self._plan_executor = plan_executor or PlanExecutor(
            tool_executor,
            planner=planner,
            validator=self._validator,
            resolver=self._resolver,
            summarizer=planner.llm,
        )
        self._execution_critic = execution_critic or ExecutionCritic(planner.llm)
        self._replanning_controller = replanning_controller or ReplanningController(
            planner,
            self._validator,
        )
        self._graph_hook = graph_hook

    @property
    def planner(self) -> PlannerAgent:
        return self._planner

    async def run(self, user_query: str, *, session_id: str = "default") -> PlanExecuteResponse:
        logger.info("Plan orchestration started: session=%s", session_id)

        plan = await self._planner.create_plan(user_query)
        self._validator.assert_valid(plan)

        state = PlanState.from_plan(plan, session_id=session_id)
        state.global_context.update(self._resolver.enrich_context_from_query(user_query))

        if self._graph_hook:
            await self._graph_hook.on_plan_created(plan, state)

        state = await self._plan_executor.execute(plan, state)

        execution_critique = None
        replan_history: list[ReplanningResult] = []

        while True:
            final_result = self._synthesize_final(state.plan, state)

            if self._execution_critic.enabled:
                execution_critique = await self._execution_critic.evaluate(state, final_result)

            if not execution_critique or not execution_critique.need_replan:
                break

            outcome = await self._replanning_controller.handle(execution_critique, state)
            replan_history.append(outcome.result)

            if not outcome.result.replanned:
                break

            state = outcome.updated_state
            plan = state.plan
            state = await self._plan_executor.execute(plan, state)

        final_result = self._synthesize_final(state.plan, state)
        trace = self._build_execution_trace(state)

        if self._graph_hook:
            await self._graph_hook.on_plan_finished(state, final_result)

        return PlanExecuteResponse(
            session_id=session_id,
            plan=state.plan,
            execution_trace=trace,
            tool_trace_json=self._tool_executor.export_trace_json(),
            final_result=final_result,
            state_summary=state.summary(),
            execution_critique=execution_critique,
            replan_history=replan_history,
        )

    @staticmethod
    def _build_execution_trace(state: PlanState) -> list[ExecutionTraceEntry]:
        if state.execution_trace:
            return list(state.execution_trace)

        entries: list[ExecutionTraceEntry] = []
        for step in sorted(state.plan.steps, key=lambda s: s.id):
            result = state.step_results.get(step.id)
            entries.append(
                ExecutionTraceEntry(
                    step_id=step.id,
                    task=step.task,
                    status=state.get_step_status(step.id),
                    tool_name=result.tool_name if result else step.tool_hint,
                    success=(result.status == StepStatus.COMPLETED if result else None),
                    error=result.error if result else None,
                    attempt=result.attempt if result else 1,
                    recovery_action=result.recovery_action if result else None,
                ),
            )
        return entries

    @staticmethod
    def _synthesize_final(plan: Plan, state: PlanState) -> str:
        return synthesize_final_result(plan, state)
