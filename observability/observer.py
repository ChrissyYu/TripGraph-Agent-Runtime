"""Graph runtime metrics observer."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from observability.context import current_trace_id
from observability.logging.structured import log_event
from observability.metrics.collector import MetricsCollector
from observability.metrics.models import ExecutionMetrics
from persistence.context import current_execution_id, current_session_id
from tools.tracing import ToolTraceRecord


@dataclass
class MetricsContext:
    execution_id: str
    session_id: str
    trace_id: str
    query: str
    graph_id: str | None
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    perf_start: float = field(default_factory=time.perf_counter)
    node_starts: dict[str, float] = field(default_factory=dict)
    owns_execution_id: bool = False


class MetricsObserver:
    """Non-blocking observer for graph/tool metrics."""

    def __init__(self, collector: MetricsCollector, *, enabled: bool = True) -> None:
        self._collector = collector
        self._enabled = enabled
        self._contexts: dict[str, MetricsContext] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def begin(
        self,
        *,
        session_id: str,
        query: str,
        graph_id: str | None = None,
        execution_id: str | None = None,
        trace_id: str | None = None,
    ) -> MetricsContext:
        exec_id = execution_id or current_execution_id.get() or str(uuid4())
        trace = trace_id or current_trace_id.get() or str(uuid4())
        current_trace_id.set(trace)

        ctx = MetricsContext(
            execution_id=exec_id,
            session_id=session_id,
            trace_id=trace,
            query=query,
            graph_id=graph_id,
        )
        if current_execution_id.get() is None:
            current_execution_id.set(exec_id)
            current_session_id.set(session_id)
            ctx.owns_execution_id = True
        self._contexts[exec_id] = ctx

        if not self._enabled:
            return ctx

        metrics = ExecutionMetrics(
            execution_id=exec_id,
            session_id=session_id,
            trace_id=trace,
            query=query,
            graph_id=graph_id,
            started_at=ctx.start_time,
        )
        self._collector.record_execution_start(metrics)
        log_event(
            "start",
            execution_id=exec_id,
            trace_id=trace,
            metadata={"session_id": session_id, "graph_id": graph_id, "query": query},
        )
        return ctx

    def on_graph_event(self, ctx: MetricsContext, event: dict[str, Any]) -> None:
        if not self._enabled:
            return

        event_type = event.get("type")
        if event_type == "node_start":
            node_id = event["node_id"]
            ctx.node_starts[node_id] = time.perf_counter()
            log_event(
                "start",
                node_id=node_id,
                execution_id=ctx.execution_id,
                trace_id=ctx.trace_id,
                metadata={"sequence": event.get("sequence")},
            )
        elif event_type == "node_end":
            self._record_node_end(ctx, event)

    def finish(
        self,
        ctx: MetricsContext,
        *,
        status: str = "completed",
        error_message: str | None = None,
    ) -> None:
        elapsed_ms = (time.perf_counter() - ctx.perf_start) * 1000
        self._contexts.pop(ctx.execution_id, None)

        if ctx.owns_execution_id:
            current_execution_id.set(None)
            current_session_id.set(None)

        if not self._enabled:
            return

        self._collector.record_execution_end(
            ctx.execution_id,
            graph_execution_time_ms=elapsed_ms,
            status=status,
        )
        log_event(
            "end" if status == "completed" else "error",
            execution_id=ctx.execution_id,
            trace_id=ctx.trace_id,
            latency_ms=elapsed_ms,
            metadata={"status": status, "error": error_message},
        )

    def on_tool_record(self, entry: ToolTraceRecord) -> None:
        if not self._enabled:
            return

        execution_id = current_execution_id.get()
        if execution_id is None:
            return

        self._collector.record_tool_call(
            execution_id,
            call_id=entry.call_id,
            tool_name=entry.tool_name,
            latency_ms=entry.latency_ms,
            success=entry.success,
            attempt=entry.attempt,
            max_attempts=entry.max_attempts,
            is_fallback=entry.is_fallback,
            error=entry.error,
        )
        log_event(
            "end" if entry.success else "error",
            execution_id=execution_id,
            trace_id=current_trace_id.get(),
            latency_ms=entry.latency_ms,
            metadata={
                "tool_name": entry.tool_name,
                "attempt": entry.attempt,
                "success": entry.success,
            },
        )

    def _record_node_end(self, ctx: MetricsContext, event: dict[str, Any]) -> None:
        node_id = event["node_id"]
        started = ctx.node_starts.pop(node_id, None)
        latency_ms = (time.perf_counter() - started) * 1000 if started is not None else 0.0
        sequence = event.get("sequence", 0)

        self._collector.record_node_latency(
            ctx.execution_id,
            node_id=node_id,
            sequence=sequence,
            latency_ms=latency_ms,
        )
        log_event(
            "end",
            node_id=node_id,
            execution_id=ctx.execution_id,
            trace_id=ctx.trace_id,
            latency_ms=latency_ms,
            metadata={"sequence": sequence},
        )
