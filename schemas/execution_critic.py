"""Execution critic result schemas."""

from pydantic import BaseModel, Field


class ExecutionCritique(BaseModel):
    """Quality assessment after plan execution."""

    score: float = Field(ge=0.0, le=1.0, description="Overall execution quality 0-1")
    critique: str
    need_replan: bool
    goal_completed: bool
    missing_info: list[str] = Field(default_factory=list)
