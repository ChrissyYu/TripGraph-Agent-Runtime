"""Reliability policy for tool execution."""

from pydantic import BaseModel, Field


class ToolReliabilityPolicy(BaseModel):
    """Retry, timeout, and fallback configuration."""

    max_retries: int = Field(default=2, ge=0, description="Retries after the first failed attempt")
    timeout_sec: float | None = Field(default=30.0, gt=0, description="Per-attempt async timeout")
    fallback_tools: dict[str, str] = Field(
        default_factory=dict,
        description="Map primary tool name → fallback tool name",
    )

    @property
    def max_attempts(self) -> int:
        return 1 + self.max_retries
