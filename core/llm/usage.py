"""LLM token usage models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated: bool = False


class LLMCompletion(BaseModel):
    text: str
    usage: LLMUsage = Field(default_factory=LLMUsage)
    model: str | None = None
    provider: str | None = None


def estimate_token_usage(
    messages: list,
    response_text: str,
) -> LLMUsage:
    """Rough token estimate when provider usage is unavailable (~4 chars/token)."""
    prompt_chars = sum(len(getattr(m, "content", str(m))) for m in messages)
    completion_chars = len(response_text)
    prompt_tokens = max(1, prompt_chars // 4)
    completion_tokens = max(1, completion_chars // 4)
    return LLMUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        estimated=True,
    )
