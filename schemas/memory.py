"""Memory module schemas."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MemoryScope(StrEnum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    EPISODIC = "episodic"


class MemoryEntry(BaseModel):
    session_id: str
    key: str
    content: str
    scope: MemoryScope = MemoryScope.SHORT_TERM
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MemoryQuery(BaseModel):
    session_id: str
    key: str | None = None
    scope: MemoryScope | None = None
    limit: int = Field(default=20, ge=1, le=500)
