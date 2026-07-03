"""Tool selection router result schemas."""

from enum import StrEnum

from pydantic import BaseModel, Field


class ToolRouterStrategy(StrEnum):
    RULE_BASED = "rule_based"
    EMBEDDING = "embedding"
    LLM = "llm"


class ToolAlternative(BaseModel):
    tool: str
    confidence: float = Field(ge=0.0, le=1.0)


class ToolSelectionResult(BaseModel):
    task: str
    best_tool: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    alternatives: list[ToolAlternative] = Field(default_factory=list)
    strategy: ToolRouterStrategy
