"""Low-level SSE formatting helpers."""

import json
from typing import Any

from schemas.streaming import StreamEvent


def format_sse(event: StreamEvent) -> str:
    """Format a StreamEvent as an SSE frame."""
    payload = json.dumps(
        {"event": event.event.value, "data": event.data, "session_id": event.session_id},
        ensure_ascii=False,
    )
    return f"event: {event.event.value}\ndata: {payload}\n\n"


def format_sse_comment(comment: str) -> str:
    """Format an SSE comment (used for heartbeats)."""
    return f": {comment}\n\n"


def format_sse_data(event_name: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_name}\ndata: {payload}\n\n"
