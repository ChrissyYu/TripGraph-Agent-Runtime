"""Plan execution failure recovery policies."""

from enum import StrEnum

from pydantic import BaseModel, Field


class FailurePolicy(StrEnum):
    RETRY = "retry"
    SKIP = "skip"
    REPLAN = "replan"


class PlanFailureConfig(BaseModel):
    """Configuration for plan-level step failure handling."""

    failure_policy: FailurePolicy = FailurePolicy.RETRY
    step_max_retries: int = Field(default=2, ge=0, description="Retries per step when policy=retry")
    max_replan_attempts: int = Field(default=1, ge=0, description="Max replans per execution")
