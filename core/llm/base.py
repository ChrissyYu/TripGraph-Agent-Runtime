"""LLM client protocol."""

from typing import Any, Protocol

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMClient(Protocol):
    """Protocol for text-completion LLM backends."""

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        response_json: bool = False,
    ) -> str:
        """Return the model text response."""
