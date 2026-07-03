"""Production JSON logger with trace and execution context."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from observability.context import current_trace_id
from persistence.context import current_execution_id


class JsonLogFormatter(logging.Formatter):
    """Emit standardized JSON log lines to stdout."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "trace_id": getattr(record, "trace_id", None) or current_trace_id.get(),
            "execution_id": getattr(record, "execution_id", None) or current_execution_id.get(),
            "module": getattr(record, "module_name", None) or _module_from_record(record),
            "event": getattr(record, "event_name", None) or record.getMessage(),
            "message": record.getMessage(),
        }

        if getattr(record, "latency_ms", None) is not None:
            payload["latency_ms"] = record.latency_ms

        node = getattr(record, "node", None)
        if node is not None:
            payload["node"] = node

        json_fields = getattr(record, "json_fields", None)
        if isinstance(json_fields, dict):
            payload.update(json_fields)

        observability = getattr(record, "observability", None)
        if isinstance(observability, dict):
            if observability.get("trace_id"):
                payload["trace_id"] = observability["trace_id"]
            if observability.get("execution_id"):
                payload["execution_id"] = observability["execution_id"]
            if observability.get("node_id"):
                payload["node"] = observability["node_id"]
            if observability.get("event_type"):
                payload["event"] = observability["event_type"]
            if observability.get("latency_ms") is not None:
                payload["latency_ms"] = observability["latency_ms"]
            metadata = observability.get("metadata")
            if isinstance(metadata, dict) and metadata:
                payload["metadata"] = metadata

        return json.dumps(payload, ensure_ascii=False, default=str)


def log_json(
    module: str,
    event: str,
    *,
    level: int = logging.INFO,
    latency_ms: float | None = None,
    node: str | None = None,
    trace_id: str | None = None,
    execution_id: str | None = None,
    **fields: Any,
) -> None:
    """Write a structured JSON log entry."""
    logger = logging.getLogger(module)
    extra: dict[str, Any] = {
        "module_name": module,
        "event_name": event,
    }
    if latency_ms is not None:
        extra["latency_ms"] = latency_ms
    if node is not None:
        extra["node"] = node
    if trace_id is not None:
        extra["trace_id"] = trace_id
    if execution_id is not None:
        extra["execution_id"] = execution_id
    if fields:
        extra["json_fields"] = fields
    logger.log(level, event, extra=extra)


def _module_from_record(record: logging.LogRecord) -> str:
    name = record.name
    if name == "observability.events":
        return "observability"
    if name.startswith("graph."):
        return "graph_runtime"
    if name.startswith("tools."):
        return "tool_executor"
    if name.startswith("agents.") or name.startswith("plan."):
        return name.split(".", 1)[0]
    return name.split(".")[-1] if "." in name else name
