"""Plan-driven agent schemas."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from schemas.execution_critic import ExecutionCritique


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStep(BaseModel):
    id: int
    task: str
    tool_hint: str | None = None
    dependency: list[int] | None = None


class Plan(BaseModel):
    goal: str
    steps: list[PlanStep] = Field(default_factory=list)


class PlanValidationReport(BaseModel):
    """Result of plan validation."""

    success: bool
    errors: list[str] = Field(default_factory=list)

    def readable_message(self) -> str:
        if self.success:
            return "Plan validation passed."
        return "Plan validation failed:\n- " + "\n- ".join(self.errors)


class StepResult(BaseModel):
    step_id: int
    task: str
    status: StepStatus
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    observation: Any = None
    error: str | None = None
    attempt: int = 1
    recovery_action: str | None = None


class PlanExecuteRequest(BaseModel):
    session_id: str = Field(default="default", min_length=1)
    query: str = Field(..., min_length=1, description="User planning request")


class ExecutionTraceEntry(BaseModel):
    step_id: int
    task: str
    status: StepStatus
    tool_name: str | None = None
    success: bool | None = None
    error: str | None = None
    attempt: int = 1
    recovery_action: str | None = None


class PlanExecuteResponse(BaseModel):
    session_id: str
    plan: Plan
    execution_trace: list[ExecutionTraceEntry]
    tool_trace_json: str
    final_result: str
    state_summary: dict[str, Any]
    execution_critique: ExecutionCritique | None = None
    replan_history: list["ReplanningResult"] = Field(default_factory=list)


from schemas.replanning import ReplanningResult  # noqa: E402

PlanExecuteResponse.model_rebuild(_types_namespace={"ReplanningResult": ReplanningResult})
