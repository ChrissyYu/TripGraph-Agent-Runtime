"""Execute structured plans with failure recovery."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from config.settings import Settings, get_settings
from core.exceptions import AgentLoopError
from core.logging import get_logger
from plan.context_compression import ContextCompressionConfig, ContextCompressor
from plan.failure_policy import FailurePolicy, PlanFailureConfig
from plan.graph import PlanExecutionGraph
from plan.resolver import StepToolResolver
from plan.state import PlanState
from plan.validator import PlanValidator
from schemas.plan import ExecutionTraceEntry, Plan, PlanStep, StepResult, StepStatus
from schemas.plan_graph import GraphNodeStatus, PlanExecutionGraphSnapshot
from tools.executor import ToolExecutor
from tools.policy.engine import ToolPolicyEngine
from tools.policy.models import ToolPolicyDecision, ToolPolicyTraceEntry
from tools.policy.trace import ToolPolicyTracer

if TYPE_CHECKING:
    from core.llm.base import LLMClient

logger = get_logger(__name__)


class PlanExecutor:
    """Runs plan steps with retry / skip / replan failure policies."""

    def __init__(
        self,
        tool_executor: ToolExecutor,
        *,
        planner=None,
        validator: PlanValidator | None = None,
        resolver: StepToolResolver | None = None,
        failure_config: PlanFailureConfig | None = None,
        settings: Settings | None = None,
        summarizer: LLMClient | None = None,
        context_compression: ContextCompressionConfig | None = None,
        tool_policy_engine: ToolPolicyEngine | None = None,
        tool_policy_tracer: ToolPolicyTracer | None = None,
    ) -> None:
        self._tool_executor = tool_executor
        self._planner = planner
        self._validator = validator
        self._resolver = resolver or StepToolResolver()
        self._tool_policy_engine = tool_policy_engine
        self._tool_policy_tracer = tool_policy_tracer
        cfg = settings or get_settings()
        self._settings = cfg
        if failure_config is not None:
            self._failure_config = failure_config
        else:
            self._failure_config = PlanFailureConfig(
                failure_policy=FailurePolicy(cfg.plan_failure_policy),
                step_max_retries=cfg.plan_step_max_retries,
                max_replan_attempts=cfg.plan_max_replan_attempts,
            )
        self._context_compressor = ContextCompressor(
            summarizer,
            config=context_compression,
            settings=cfg,
        )
        self._replan_attempts = 0
        self._execution_graph: PlanExecutionGraph | None = None

    @property
    def context_compressor(self) -> ContextCompressor:
        return self._context_compressor

    @property
    def execution_graph(self) -> PlanExecutionGraph | None:
        return self._execution_graph

    def get_graph_snapshot(self) -> PlanExecutionGraphSnapshot:
        if self._execution_graph is None:
            raise RuntimeError("No execution graph available; run execute() first")
        return self._execution_graph.get_graph_snapshot()

    def export_graph_json(self, *, indent: int = 2) -> str:
        if self._execution_graph is None:
            raise RuntimeError("No execution graph available; run execute() first")
        return self._execution_graph.export_graph_json(indent=indent)

    async def execute(self, plan: Plan, state: PlanState) -> PlanState:
        self._execution_graph = PlanExecutionGraph.from_plan(plan, session_id=state.session_id)
        self._sync_graph(state)
        logger.info(
            "Executing plan: %s (%d steps, policy=%s)",
            plan.goal,
            len(plan.steps),
            self._failure_config.failure_policy.value,
        )

        while not state.all_steps_finished():
            step_id = state.next_executable_step()
            if step_id is None:
                pending = state.unfinished_step_ids()
                if pending:
                    raise AgentLoopError(
                        f"Plan deadlock: steps {pending} cannot run (unmet dependencies?)",
                    )
                break

            step = state._find_step(step_id)
            await self._run_step_with_recovery(step, state)
            self._sync_graph(state)

        state.current_step = None
        self._sync_graph(state)
        return state

    async def _run_step_with_recovery(self, step: PlanStep, state: PlanState) -> None:
        policy = self._failure_config.failure_policy
        max_attempts = (
            1 + self._failure_config.step_max_retries
            if policy == FailurePolicy.RETRY
            else 1
        )

        for attempt in range(1, max_attempts + 1):
            state.current_step = step.id
            state.set_step_status(step.id, StepStatus.RUNNING)
            self._update_graph_node(step.id, GraphNodeStatus.RUNNING)

            result = await self._execute_step(step, state, attempt=attempt)
            state.record_step_result(result)
            self._record_trace(state, step, result)

            if result.status != StepStatus.FAILED:
                self._merge_observation_into_context(step.id, result, state)
                await self._maybe_compress_context(state)
                state.current_step = None
                return

            logger.warning("Step %d failed (attempt %d/%d): %s", step.id, attempt, max_attempts, result.error)

            if policy == FailurePolicy.RETRY and attempt < max_attempts:
                state.reset_step_for_retry(step.id)
                self._update_graph_node(step.id, GraphNodeStatus.PENDING)
                continue

            if policy == FailurePolicy.SKIP:
                skipped = result.model_copy(
                    update={"status": StepStatus.SKIPPED, "recovery_action": "skip"},
                )
                state.record_step_result(skipped)
                self._record_trace(
                    state,
                    step,
                    skipped,
                    recovery_action="skip",
                    override_status=StepStatus.SKIPPED,
                )
                state.current_step = None
                return

            if policy == FailurePolicy.REPLAN:
                if self._replan_attempts >= self._failure_config.max_replan_attempts:
                    raise AgentLoopError(
                        f"Step {step.id} failed and max replan attempts "
                        f"({self._failure_config.max_replan_attempts}) exceeded",
                    )
                self._replan_attempts += 1
                await self._handle_replan(step, state, result.error or "unknown error")
                state.current_step = None
                return

            raise AgentLoopError(result.error or f"Step {step.id} failed")

        raise AgentLoopError(f"Step {step.id} failed after {max_attempts} attempts")

    async def _handle_replan(
        self,
        failed_step: PlanStep,
        state: PlanState,
        error: str,
    ) -> None:
        if self._planner is None:
            raise AgentLoopError("Replan policy requires a PlannerAgent instance")

        failed = state.step_results.get(failed_step.id)
        if failed:
            replan_marker = failed.model_copy(update={"recovery_action": "replan"})
            self._record_trace(
                state,
                failed_step,
                replan_marker,
                recovery_action="replan",
                override_status=StepStatus.FAILED,
            )

        new_steps = await self._planner.replan_unfinished_steps(
            state,
            failed_step_id=failed_step.id,
            error=error,
        )

        state.apply_replanned_steps(new_steps)

        if self._validator:
            self._validator.assert_valid(state.plan)

        if self._execution_graph:
            self._execution_graph.rebuild_from_plan(state.plan)
            self._sync_graph(state)

        logger.info(
            "Replanned %d steps after failure on step %d; plan now has %d steps",
            len(new_steps),
            failed_step.id,
            len(state.plan.steps),
        )

    async def _execute_step(
        self,
        step: PlanStep,
        state: PlanState,
        *,
        attempt: int = 1,
    ) -> StepResult:
        if not step.tool_hint:
            return StepResult(
                step_id=step.id,
                task=step.task,
                status=StepStatus.COMPLETED,
                observation={"message": f"Completed without tool: {step.task}"},
                attempt=attempt,
            )

        tool_args = self._resolver.resolve(step, state)
        if tool_args is None:
            return StepResult(
                step_id=step.id,
                task=step.task,
                status=StepStatus.SKIPPED,
                tool_name=step.tool_hint,
                error=f"No arguments resolved for tool_hint={step.tool_hint}",
                attempt=attempt,
            )

        observation = await self._tool_executor.execute_llm_call(
            {"tool": step.tool_hint, "args": tool_args},
            call_id=f"plan-step-{step.id}-a{attempt}",
        )

        policy_decision = self._get_policy_decision(step.id, state)
        recovery_action: str | None = None
        final_tool = step.tool_hint

        if (
            not observation.success
            and self._settings.tool_policy_enabled
            and self._settings.tool_policy_mcp_fallback_enabled
            and policy_decision
            and policy_decision.fallback_candidates
        ):
            fallback_result = await self._try_policy_fallback(
                step=step,
                state=state,
                tool_args=tool_args,
                attempt=attempt,
                failed_tool=step.tool_hint or "",
                policy_decision=policy_decision,
                failure_reason=observation.error or "tool execution failed",
            )
            if fallback_result is not None:
                observation, final_tool, recovery_action = fallback_result

        if not observation.success:
            return StepResult(
                step_id=step.id,
                task=step.task,
                status=StepStatus.FAILED,
                tool_name=final_tool,
                tool_args=tool_args,
                error=observation.error,
                attempt=attempt,
                recovery_action=recovery_action,
            )

        return StepResult(
            step_id=step.id,
            task=step.task,
            status=StepStatus.COMPLETED,
            tool_name=final_tool,
            tool_args=tool_args,
            observation=observation.output,
            attempt=attempt,
            recovery_action=recovery_action,
        )

    def _get_policy_decision(self, step_id: int, state: PlanState) -> ToolPolicyDecision | None:
        raw = state.global_context.get("tool_policy_decisions", {}).get(str(step_id))
        if not raw:
            return None
        return ToolPolicyDecision.model_validate(raw)

    async def _try_policy_fallback(
        self,
        *,
        step: PlanStep,
        state: PlanState,
        tool_args: dict,
        attempt: int,
        failed_tool: str,
        policy_decision: ToolPolicyDecision,
        failure_reason: str,
    ) -> tuple[Any, str, str] | None:
        if self._tool_policy_engine is None:
            return None

        for fallback_tool in policy_decision.fallback_candidates:
            if not self._tool_executor.registry.has(fallback_tool):
                continue
            logger.warning(
                "Policy fallback: %s failed → trying %s (step %d)",
                failed_tool,
                fallback_tool,
                step.id,
            )
            fallback_obs = await self._tool_executor.execute_llm_call(
                {"tool": fallback_tool, "args": tool_args},
                call_id=f"plan-step-{step.id}-a{attempt}-policy-fb",
            )
            recovery_action = self._tool_policy_engine.recovery_action_for_fallback(
                failed_tool,
                fallback_tool,
            )
            if self._tool_policy_tracer is not None:
                entry = ToolPolicyTraceEntry(
                    **policy_decision.model_dump(),
                    step_id=step.id,
                    task=step.task,
                )
                self._tool_policy_tracer.record_fallback(
                    entry,
                    fallback_tool=fallback_tool,
                    failure_reason=failure_reason,
                    recovery_action=recovery_action,
                )
            updated = policy_decision.model_copy(
                update={
                    "fallback_used": True,
                    "fallback_tool": fallback_tool,
                    "failure_reason": failure_reason,
                },
            )
            state.global_context.setdefault("tool_policy_decisions", {})[
                str(step.id)
            ] = updated.model_dump_json_safe()

            if fallback_obs.success:
                step.tool_hint = fallback_tool
                return fallback_obs, fallback_tool, recovery_action

        return None

    @staticmethod
    def _record_trace(
        state: PlanState,
        step: PlanStep,
        result: StepResult,
        *,
        recovery_action: str | None = None,
        override_status: StepStatus | None = None,
    ) -> None:
        state.append_trace(
            ExecutionTraceEntry(
                step_id=step.id,
                task=step.task,
                status=override_status or result.status,
                tool_name=result.tool_name or step.tool_hint,
                success=result.status == StepStatus.COMPLETED,
                error=result.error,
                attempt=result.attempt,
                recovery_action=recovery_action or result.recovery_action,
            ),
        )

    @staticmethod
    def _merge_observation_into_context(
        step_id: int,
        result: StepResult,
        state: PlanState,
    ) -> None:
        state.global_context.setdefault("step_outputs", {})
        state.global_context["step_outputs"][step_id] = result.observation
        if result.tool_name:
            state.global_context.setdefault("tool_outputs", {})
            state.global_context["tool_outputs"][result.tool_name] = result.observation

    async def _maybe_compress_context(self, state: PlanState) -> None:
        await self._context_compressor.maybe_compress(state)

    def _sync_graph(self, state: PlanState) -> None:
        if self._execution_graph is not None:
            self._execution_graph.sync_from_state(state)

    def _update_graph_node(
        self,
        step_id: int,
        status: GraphNodeStatus,
        *,
        error: str | None = None,
    ) -> None:
        if self._execution_graph is not None:
            self._execution_graph.set_node_status(step_id, status, error=error)
