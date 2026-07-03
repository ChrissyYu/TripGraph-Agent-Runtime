"""In-memory metrics store keyed by execution_id."""

from __future__ import annotations

from observability.metrics.models import ExecutionMetrics


class MetricsStore:
    """Thread-safe enough for asyncio single-loop usage."""

    def __init__(self) -> None:
        self._executions: dict[str, ExecutionMetrics] = {}

    def put(self, metrics: ExecutionMetrics) -> None:
        self._executions[metrics.execution_id] = metrics

    def get(self, execution_id: str) -> ExecutionMetrics | None:
        return self._executions.get(execution_id)

    def upsert(self, execution_id: str, factory) -> ExecutionMetrics:
        existing = self._executions.get(execution_id)
        if existing is None:
            existing = factory()
            self._executions[execution_id] = existing
        return existing

    def list_execution_ids(self) -> list[str]:
        return list(self._executions.keys())
