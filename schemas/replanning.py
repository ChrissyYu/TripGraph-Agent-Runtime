"""Replanning controller result schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from schemas.plan import Plan


class ReplanningResult(BaseModel):
    """Outcome of a critic-driven replan attempt."""

    replanned: bool
    new_plan: Plan
    replan_reason: str | None = None
    replan_attempt: int = 0
    skipped_reason: str | None = None
    repair_applied: bool = False
    fallback_used: bool = False
    repair_notes: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    completed_step_overrides: list[str] = Field(default_factory=list)


def _rebuild_models() -> None:
    from schemas.plan import Plan

    ReplanningResult.model_rebuild(_types_namespace={"Plan": Plan})


_rebuild_models()
