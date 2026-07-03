"""Plan execution state manager."""

from __future__ import annotations

from typing import Any

from schemas.plan import ExecutionTraceEntry, Plan, PlanStep, StepResult, StepStatus


class PlanState:
    """Tracks plan progress, results, shared context, and execution trace."""

    def __init__(self, plan: Plan, *, session_id: str = "default") -> None:
        self.plan = plan
        self.session_id = session_id
        self.current_step: int | None = None
        self.completed_steps: list[int] = []
        self.step_results: dict[int, StepResult] = {}
        self.global_context: dict[str, Any] = {}
        self.execution_trace: list[ExecutionTraceEntry] = []
        self._step_status: dict[int, StepStatus] = {
            step.id: StepStatus.PENDING for step in plan.steps
        }

    @classmethod
    def from_plan(cls, plan: Plan, *, session_id: str = "default") -> PlanState:
        return cls(plan, session_id=session_id)

    def get_step_status(self, step_id: int) -> StepStatus:
        return self._step_status[step_id]

    def set_step_status(self, step_id: int, status: StepStatus) -> None:
        self._step_status[step_id] = status
        if status == StepStatus.COMPLETED and step_id not in self.completed_steps:
            self.completed_steps.append(step_id)

    def record_step_result(self, result: StepResult) -> None:
        self.step_results[result.step_id] = result
        self.set_step_status(result.step_id, result.status)

    def append_trace(self, entry: ExecutionTraceEntry) -> None:
        self.execution_trace.append(entry)

    def reset_step_for_retry(self, step_id: int) -> None:
        self._step_status[step_id] = StepStatus.PENDING
        self.step_results.pop(step_id, None)
        if step_id in self.completed_steps:
            self.completed_steps.remove(step_id)

    def mark_step_skipped(self, step_id: int, *, error: str | None = None) -> None:
        self.set_step_status(step_id, StepStatus.SKIPPED)

    def finished_step_ids(self) -> set[int]:
        return {
            step_id
            for step_id, status in self._step_status.items()
            if status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
        }

    def unfinished_step_ids(self) -> list[int]:
        return [
            step.id
            for step in self.plan.steps
            if self.get_step_status(step.id)
            not in (StepStatus.COMPLETED, StepStatus.SKIPPED)
        ]

    def apply_replanned_steps(self, new_steps: list[PlanStep]) -> None:
        """Replace unfinished steps while preserving completed ones."""
        completed_ids = self.finished_step_ids()
        kept_steps = [s for s in self.plan.steps if s.id in completed_ids]

        max_id = max(completed_ids) if completed_ids else 0
        remapped: list[PlanStep] = []
        for index, step in enumerate(new_steps, start=1):
            new_id = max_id + index
            deps = list(step.dependency or [])
            remapped.append(
                PlanStep(
                    id=new_id,
                    task=step.task,
                    tool_hint=step.tool_hint,
                    dependency=deps if deps else None,
                ),
            )

        removed_ids = {s.id for s in self.plan.steps if s.id not in completed_ids}
        for step_id in removed_ids:
            self._step_status.pop(step_id, None)
            self.step_results.pop(step_id, None)

        self.plan.steps = kept_steps + remapped
        for step in remapped:
            self._step_status[step.id] = StepStatus.PENDING

    def restore_completed_step_snapshots(self, snapshots: dict[int, PlanStep]) -> list[str]:
        """Restore completed steps when replan output modified immutable steps."""
        warnings: list[str] = []
        for step_id, original in snapshots.items():
            for index, step in enumerate(self.plan.steps):
                if step.id != step_id:
                    continue
                unchanged = (
                    step.task == original.task
                    and step.tool_hint == original.tool_hint
                    and (step.dependency or []) == (original.dependency or [])
                )
                if not unchanged:
                    self.plan.steps[index] = original.model_copy(deep=True)
                    warnings.append(
                        f"Restored immutable completed step {step_id}: "
                        f"kept task={original.task!r}",
                    )
                break
        return warnings

    def remap_step_status(self, id_map: dict[int, int]) -> None:
        """Rebuild step status/results after plan step ids are renumbered."""
        if not id_map:
            return

        new_status: dict[int, StepStatus] = dict(self._step_status)
        new_results: dict[int, StepResult] = {
            step_id: result.model_copy(deep=True)
            for step_id, result in self.step_results.items()
        }

        for old_id, new_id in id_map.items():
            if old_id in new_status:
                new_status[new_id] = new_status.pop(old_id)
            if old_id in new_results:
                new_results[new_id] = new_results.pop(old_id).model_copy(
                    update={"step_id": new_id},
                )

        plan_ids = {step.id for step in self.plan.steps}
        new_status = {step_id: status for step_id, status in new_status.items() if step_id in plan_ids}
        new_results = {
            step_id: result for step_id, result in new_results.items() if step_id in plan_ids
        }

        for step in self.plan.steps:
            if step.id not in new_status:
                new_status[step.id] = StepStatus.PENDING

        self._step_status = new_status
        self.step_results = new_results
        self.completed_steps = [
            step_id
            for step_id, status in self._step_status.items()
            if status == StepStatus.COMPLETED
        ]

    def snapshot_for_replan(self) -> dict[str, Any]:
        """Capture mutable plan state so a failed replan can be rolled back."""
        return {
            "plan": self.plan.model_copy(deep=True),
            "step_status": dict(self._step_status),
            "step_results": {k: v.model_copy(deep=True) for k, v in self.step_results.items()},
            "completed_steps": list(self.completed_steps),
            "execution_trace": list(self.execution_trace),
        }

    def restore_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.plan = snapshot["plan"]
        self._step_status = snapshot["step_status"]
        self.step_results = snapshot["step_results"]
        self.completed_steps = snapshot["completed_steps"]
        self.execution_trace = snapshot["execution_trace"]

    def dependencies_met(self, step_id: int) -> bool:
        step = self._find_step(step_id)
        if not step.dependency:
            return True
        finished = self.finished_step_ids()
        return all(dep in finished for dep in step.dependency)

    def next_executable_step(self) -> int | None:
        for step in sorted(self.plan.steps, key=lambda s: s.id):
            if self.get_step_status(step.id) != StepStatus.PENDING:
                continue
            if self.dependencies_met(step.id):
                return step.id
        return None

    def all_steps_finished(self) -> bool:
        return all(
            self.get_step_status(step.id)
            in (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.SKIPPED)
            for step in self.plan.steps
        )

    def replan_context(self) -> dict[str, Any]:
        """Snapshot passed to planner when replanning unfinished steps."""
        return {
            "goal": self.plan.goal,
            "session_id": self.session_id,
            "completed_steps": sorted(self.completed_steps),
            "unfinished_step_ids": self.unfinished_step_ids(),
            "step_results": {
                str(k): v.model_dump() for k, v in self.step_results.items()
            },
            "global_context": dict(self.global_context),
            "execution_trace": [e.model_dump() for e in self.execution_trace],
        }

    def summary(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "goal": self.plan.goal,
            "current_step": self.current_step,
            "completed_steps": list(self.completed_steps),
            "global_context": dict(self.global_context),
            "step_status": {str(k): v.value for k, v in self._step_status.items()},
            "execution_trace_count": len(self.execution_trace),
            "compression_count": int(
                self.global_context.get("_compression_meta", {}).get("compression_count", 0),
            ),
        }

    def _find_step(self, step_id: int) -> PlanStep:
        for step in self.plan.steps:
            if step.id == step_id:
                return step
        raise KeyError(f"Step not found: {step_id}")
