"""Structured JSON observability logging."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from observability.context import current_trace_id
from persistence.context import current_execution_id

OBSERVABILITY_LOGGER = "observability.events"


class StructuredJsonFormatter(logging.Formatter):
    """Emit one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        observability = getattr(record, "observability", None)
        if isinstance(observability, dict):
            payload.update(observability)
        return json.dumps(payload, ensure_ascii=False, default=str)


def log_event(
    event_type: str,
    *,
    node_id: str | None = None,
    latency_ms: float | None = None,
    metadata: dict[str, Any] | None = None,
    level: int = logging.INFO,
    execution_id: str | None = None,
    trace_id: str | None = None,
) -> None:
    logger = logging.getLogger(OBSERVABILITY_LOGGER)
    logger.log(
        level,
        event_type,
        extra={
            "observability": {
                "trace_id": trace_id or current_trace_id.get(),
                "execution_id": execution_id or current_execution_id.get(),
                "node_id": node_id,
                "event_type": event_type,
                "latency_ms": latency_ms,
                "metadata": metadata or {},
            },
        },
    )
