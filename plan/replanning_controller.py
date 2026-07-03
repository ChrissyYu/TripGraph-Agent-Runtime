"""Critic-driven replanning with completed-step preservation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from config.settings import Settings, get_settings
from core.logging import get_logger
from plan.repair import repair_plan, repair_steps
from plan.state import PlanState
from plan.validator import PlanValidator
from schemas.execution_critic import ExecutionCritique
from schemas.plan import ExecutionTraceEntry, PlanStep, StepStatus
from schemas.replanning import ReplanningResult

if TYPE_CHECKING:
    from agents.planner import PlannerAgent

logger = get_logger(__name__)


@dataclass(frozen=True)
class ReplanningConfig:
    enabled: bool = True
    max_replan_attempts: int = 2


@dataclass
class ReplanningOutcome:
    """Runtime outcome including mutable PlanState."""

    result: ReplanningResult
    updated_state: PlanState


@dataclass
class _ReplanApplyMeta:
    repair_applied: bool = False
    fallback_used: bool = False
    repair_notes: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    completed_step_overrides: list[str] = field(default_factory=list)


class ReplanningController:
    """Decides and applies critic-driven replans while preserving completed work."""

    def __init__(
        self,
        planner: Any,
        validator: PlanValidator,
        *,
        config: ReplanningConfig | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._planner = planner
        self._validator = validator
        cfg = settings or get_settings()
        self._config = config or ReplanningConfig(
            enabled=cfg.plan_critic_replan_enabled,
            max_replan_attempts=cfg.plan_critic_max_replan_attempts,
        )
        self._attempts = 0

    @property
    def config(self) -> ReplanningConfig:
        return self._config

    @property
    def attempts_used(self) -> int:
        return self._attempts

    def reset_attempts(self) -> None:
        self._attempts = 0

    async def handle(
        self,
        critique: ExecutionCritique,
        state: PlanState,
    ) -> ReplanningOutcome:
        if not critique.need_replan:
            return self._no_replan(state, skipped_reason="critic_need_replan=false")

        if not self._config.enabled:
            return self._no_replan(state, skipped_reason="critic_replan_disabled")

        if self._attempts >= self._config.max_replan_attempts:
            logger.warning(
                "Critic replan skipped: max attempts (%d) reached",
                self._config.max_replan_attempts,
            )
            return self._no_replan(
                state,
                skipped_reason=f"max_replan_attempts={self._config.max_replan_attempts}",
            )

        return await self._replan(critique, state)

    async def _replan(
        self,
        critique: ExecutionCritique,
        state: PlanState,
    ) -> ReplanningOutcome:
        self._attempts += 1
        replan_reason = self._build_replan_reason(critique)
        completed_before = self._completed_step_snapshot(state)

        anchor_step_id = self._replan_anchor_step_id(state)
        self._record_replan_trace(state, replan_reason, anchor_step_id)

        meta = _ReplanApplyMeta()
        snapshot = state.snapshot_for_replan()

        new_steps = await self._planner.replan_from_critique(
            state,
            critique=critique,
            anchor_step_id=anchor_step_id,
        )
        applied = self._try_apply_replan_steps(
            state,
            new_steps,
            completed_before=completed_before,
            meta=meta,
        )

        if not applied:
            state.restore_snapshot(snapshot)
            logger.warning(
                "LLM replan validation failed (%s); attempting RuleBased fallback",
                "; ".join(meta.validation_errors) or "unknown",
            )
            meta = _ReplanApplyMeta(fallback_used=True)
            fallback_steps = await self._planner.rulebased_replan_from_critique(
                state,
                critique=critique,
                anchor_step_id=anchor_step_id,
            )
            applied = self._try_apply_replan_steps(
                state,
                fallback_steps,
                completed_before=completed_before,
                meta=meta,
            )
            if applied:
                self._record_recovery_trace(
                    state,
                    anchor_step_id,
                    recovery_action="replan_fallback",
                    detail="RuleBased replan fallback applied after validation failure",
                )

        if not applied:
            state.restore_snapshot(snapshot)
            logger.error(
                "Replan failed after repair and RuleBased fallback; keeping previous plan"
            )
            self._record_recovery_trace(
                state,
                anchor_step_id,
                recovery_action="replan_failed",
                detail="; ".join(meta.validation_errors) or "validation failed",
            )
            return ReplanningOutcome(
                result=ReplanningResult(
                    replanned=False,
                    new_plan=state.plan,
                    replan_reason=replan_reason,
                    replan_attempt=self._attempts,
                    skipped_reason="replan_validation_failed",
                    repair_applied=meta.repair_applied,
                    fallback_used=meta.fallback_used,
                    repair_notes=meta.repair_notes,
                    validation_errors=meta.validation_errors,
                    completed_step_overrides=meta.completed_step_overrides,
                ),
                updated_state=state,
            )

        if meta.repair_applied:
            self._record_recovery_trace(
                state,
                anchor_step_id,
                recovery_action="replan_repair",
                detail="; ".join(meta.repair_notes) or "plan repair applied",
            )

        logger.info(
            "Critic replan applied: attempt=%d kept_completed=%s new_steps=%d repair=%s fallback=%s",
            self._attempts,
            sorted(completed_before.keys()),
            len(state.plan.steps),
            meta.repair_applied,
            meta.fallback_used,
        )

        result = ReplanningResult(
            replanned=True,
            new_plan=state.plan,
            replan_reason=replan_reason,
            replan_attempt=self._attempts,
            repair_applied=meta.repair_applied,
            fallback_used=meta.fallback_used,
            repair_notes=meta.repair_notes,
            validation_errors=meta.validation_errors,
            completed_step_overrides=meta.completed_step_overrides,
        )
        return ReplanningOutcome(result=result, updated_state=state)

    def _try_apply_replan_steps(
        self,
        state: PlanState,
        new_steps: list[PlanStep],
        *,
        completed_before: dict[int, PlanStep],
        meta: _ReplanApplyMeta,
    ) -> bool:
        repaired_steps = repair_steps(new_steps)
        if repaired_steps.repaired:
            meta.repair_applied = True
            meta.repair_notes.extend(repaired_steps.notes)
            new_steps = repaired_steps.plan.steps

        pre_apply_status = dict(state._step_status)

        state.apply_replanned_steps(new_steps)
        if self._validate_or_repair_plan(state, pre_apply_status, meta):
            overrides = state.restore_completed_step_snapshots(completed_before)
            if overrides:
                meta.completed_step_overrides.extend(overrides)
                meta.repair_applied = True
            try:
                self._assert_completed_steps_preserved(state, completed_before)
                return True
            except ValueError as exc:
                meta.validation_errors = [str(exc)]
                return False
        return False

    def _validate_or_repair_plan(
        self,
        state: PlanState,
        pre_apply_status: dict[int, StepStatus],
        meta: _ReplanApplyMeta,
    ) -> bool:
        report = self._validator.validate(state.plan)
        if report.success:
            return True

        meta.validation_errors = list(report.errors)
        repair_result = repair_plan(state.plan)
        if not repair_result.repaired:
            return False

        meta.repair_applied = True
        meta.repair_notes.extend(repair_result.notes)
        state.plan = repair_result.plan
        if repair_result.id_map:
            state.remap_step_status(repair_result.id_map)
        else:
            state._step_status = pre_apply_status

        report = self._validator.validate(state.plan)
        if report.success:
            meta.validation_errors = []
            return True

        meta.validation_errors = list(report.errors)
        return False

    def _no_replan(self, state: PlanState, *, skipped_reason: str) -> ReplanningOutcome:
        result = ReplanningResult(
            replanned=False,
            new_plan=state.plan,
            replan_reason=None,
            replan_attempt=self._attempts,
            skipped_reason=skipped_reason,
        )
        return ReplanningOutcome(result=result, updated_state=state)

    @staticmethod
    def _build_replan_reason(critique: ExecutionCritique) -> str:
        parts = [critique.critique]
        if critique.missing_info:
            parts.append(f"Missing: {', '.join(critique.missing_info)}")
        parts.append(f"score={critique.score:.2f}")
        return " | ".join(parts)

    @staticmethod
    def _replan_anchor_step_id(state: PlanState) -> int:
        unfinished = state.unfinished_step_ids()
        if unfinished:
            return unfinished[0]
        failed = [
            step_id
            for step_id, status in state._step_status.items()
            if status == StepStatus.FAILED
        ]
        if failed:
            return failed[0]
        return state.completed_steps[-1] if state.completed_steps else 0

    @staticmethod
    def _record_replan_trace(
        state: PlanState,
        replan_reason: str,
        anchor_step_id: int,
    ) -> None:
        state.append_trace(
            ExecutionTraceEntry(
                step_id=anchor_step_id,
                task="[replan] critic-driven plan rewrite",
                status=StepStatus.PENDING,
                tool_name=None,
                success=None,
                error=replan_reason,
                recovery_action="critic_replan",
            ),
        )

    @staticmethod
    def _record_recovery_trace(
        state: PlanState,
        anchor_step_id: int,
        *,
        recovery_action: str,
        detail: str,
    ) -> None:
        state.append_trace(
            ExecutionTraceEntry(
                step_id=anchor_step_id,
                task=f"[replan] {recovery_action}",
                status=StepStatus.PENDING,
                tool_name=None,
                success=recovery_action != "replan_failed",
                error=detail,
                recovery_action=recovery_action,
            ),
        )

    @staticmethod
    def _completed_step_snapshot(state: PlanState) -> dict[int, PlanStep]:
        finished = state.finished_step_ids()
        return {
            step.id: step.model_copy(deep=True)
            for step in state.plan.steps
            if step.id in finished
        }

    @staticmethod
    def _assert_completed_steps_preserved(
        state: PlanState,
        completed_before: dict[int, PlanStep],
    ) -> None:
        for step_id, original in completed_before.items():
            step = next((s for s in state.plan.steps if s.id == step_id), None)
            if step is None:
                matching = [s for s in state.plan.steps if s.task == original.task]
                if not matching:
                    raise ValueError(f"Completed step {step_id} was removed during replan")
                continue
            if (
                step.task != original.task
                or step.tool_hint != original.tool_hint
                or (step.dependency or []) != (original.dependency or [])
            ):
                raise ValueError(f"Completed step {step_id} task was modified during replan")
