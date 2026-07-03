"""Request-scoped persistence context."""

from __future__ import annotations

from contextvars import ContextVar

current_execution_id: ContextVar[str | None] = ContextVar("current_execution_id", default=None)
current_session_id: ContextVar[str | None] = ContextVar("current_session_id", default=None)
