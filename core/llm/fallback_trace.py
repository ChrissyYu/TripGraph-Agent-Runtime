"""Track LLM provider fallback events for observability and smoke tests."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field

import httpx

from core.exceptions import LLMClientError


@dataclass(frozen=True)
class LLMFallbackEvent:
    caller: str
    from_provider: str
    to_provider: str = "rule_based"
    reason: str = ""
    error_type: str | None = None


_events: ContextVar[list[LLMFallbackEvent]] = ContextVar(
    "llm_fallback_events",
    default=None,
)


def _events_list() -> list[LLMFallbackEvent]:
    events = _events.get()
    if events is None:
        events = []
        _events.set(events)
    return events


def clear_fallback_events() -> None:
    _events.set([])


def record_fallback_event(
    *,
    caller: str,
    from_provider: str,
    reason: str,
    error: Exception | None = None,
) -> None:
    _events_list().append(
        LLMFallbackEvent(
            caller=caller,
            from_provider=from_provider,
            reason=reason,
            error_type=classify_llm_error(error) if error is not None else None,
        ),
    )


def get_fallback_events() -> list[LLMFallbackEvent]:
    return list(_events_list())


def classify_llm_error(error: Exception | None) -> str | None:
    if error is None:
        return None
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    message = str(error).lower()
    if "timeout" in message or "timed out" in message:
        return "timeout"
    if isinstance(error, LLMClientError):
        return "api_error"
    return "error"


def planner_fallback_summary(
    events: list[LLMFallbackEvent] | None = None,
) -> dict[str, object]:
    """Summarize whether planner used RuleBased fallback and why."""
    items = events if events is not None else get_fallback_events()
    planner_events = [event for event in items if event.caller == "planner"]
    if not planner_events:
        return {
            "planner_fallback_used": False,
            "planner_error_type": None,
            "planner_fallback_reason": None,
        }
    first = planner_events[0]
    return {
        "planner_fallback_used": True,
        "planner_error_type": first.error_type,
        "planner_fallback_reason": first.reason,
    }


def timeout_suggestion(error_type: str | None, timeout_sec: float) -> str | None:
    if error_type != "timeout":
        return None
    if timeout_sec >= 180:
        return None
    return (
        "Qwen planner timed out. Consider raising QWEN_TIMEOUT_SEC=120 or 180 "
        f"(current={timeout_sec:g}s)."
    )
