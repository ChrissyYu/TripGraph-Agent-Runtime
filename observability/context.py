"""Request-scoped observability context."""

from __future__ import annotations

from contextvars import ContextVar

current_trace_id: ContextVar[str | None] = ContextVar("current_trace_id", default=None)
