"""Async metrics collector."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from config.settings import Settings, get_settings
from core.llm.usage import LLMUsage
from observability.cost.pricing import estimate_cost_usd
from observability.metrics.models import ExecutionMetrics, LLMMetric, NodeMetric, ToolMetric
from observability.metrics.store import MetricsStore

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Non-blocking metrics recorder with in-memory aggregation."""

    def __init__(
        self,
        store: MetricsStore,
        *,
        settings: Settings | None = None,
        enabled: bool = True,
    ) -> None:
        self._store = store
        self._settings = settings or get_settings()
        self._enabled = enabled
        self._queue: asyncio.Queue[tuple[Callable[..., Awaitable[Any]], tuple[Any, ...], dict[str, Any]]] | None = None
        self._worker: asyncio.Task[None] | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def store(self) -> MetricsStore:
        return self._store

    async def start(self) -> None:
        if not self._enabled or self._worker is not None:
            return
        self._queue = asyncio.Queue(maxsize=4096)
        self._worker = asyncio.create_task(self._run(), name="metrics-writer")

    async def stop(self, *, drain_timeout: float = 5.0) -> None:
        if self._worker is None:
            return
        try:
            if self._queue is not None:
                await asyncio.wait_for(self._queue.join(), timeout=drain_timeout)
        except TimeoutError:
            logger.warning("Metrics queue drain timed out")
        self._worker.cancel()
        try:
            await self._worker
        except asyncio.CancelledError:
            pass
        self._worker = None
        self._queue = None

    async def drain(self, *, timeout: float = 5.0) -> None:
        if self._queue is None:
            return
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
        except TimeoutError:
            logger.warning("Metrics queue drain timed out")

    def submit(self, coro_fn: Callable[..., Awaitable[Any]], /, *args: Any, **kwargs: Any) -> None:
        if not self._enabled or self._queue is None:
            return
        try:
            if kwargs:

                async def _invoke() -> None:
                    await coro_fn(*args, **kwargs)

                self._queue.put_nowait((_invoke, (), {}))
            else:
                self._queue.put_nowait((coro_fn, args, {}))
        except asyncio.QueueFull:
            logger.warning("Metrics queue full; dropping metric")

    def record_execution_start(self, metrics: ExecutionMetrics) -> None:
        if not self._enabled:
            return
        self.submit(self._put_execution, metrics)

    def record_execution_end(
        self,
        execution_id: str,
        *,
        graph_execution_time_ms: float,
        status: str,
    ) -> None:
        if not self._enabled:
            return
        self.submit(
            self._finish_execution,
            execution_id,
            graph_execution_time_ms=graph_execution_time_ms,
            status=status,
        )

    def record_node_latency(
        self,
        execution_id: str,
        *,
        node_id: str,
        sequence: int,
        latency_ms: float,
        status: str = "completed",
    ) -> None:
        if not self._enabled:
            return
        self.submit(
            self._append_node,
            execution_id,
            node_id=node_id,
            sequence=sequence,
            latency_ms=latency_ms,
            status=status,
        )

    def record_tool_call(
        self,
        execution_id: str,
        *,
        call_id: str,
        tool_name: str,
        latency_ms: float,
        success: bool,
        attempt: int,
        max_attempts: int,
        is_fallback: bool,
        error: str | None,
    ) -> None:
        if not self._enabled:
            return
        self.submit(
            self._append_tool,
            execution_id,
            call_id=call_id,
            tool_name=tool_name,
            latency_ms=latency_ms,
            success=success,
            attempt=attempt,
            max_attempts=max_attempts,
            is_fallback=is_fallback,
            error=error,
        )

    def record_llm_call(
        self,
        execution_id: str,
        *,
        caller: str,
        latency_ms: float,
        usage: LLMUsage,
        model: str | None = None,
        provider: str | None = None,
    ) -> None:
        if not self._enabled:
            return
        cost = estimate_cost_usd(
            usage,
            prompt_usd_per_1k=self._settings.metrics_prompt_usd_per_1k,
            completion_usd_per_1k=self._settings.metrics_completion_usd_per_1k,
        )
        self.submit(
            self._append_llm,
            execution_id,
            caller=caller,
            latency_ms=latency_ms,
            usage=usage,
            estimated_cost_usd=cost,
            model=model,
            provider=provider,
        )

    async def _run(self) -> None:
        assert self._queue is not None
        while True:
            coro_fn, args, _kwargs = await self._queue.get()
            try:
                await coro_fn(*args)
            except Exception:
                logger.exception("Metrics write failed")
            finally:
                self._queue.task_done()

    async def _put_execution(self, metrics: ExecutionMetrics) -> None:
        self._store.put(metrics)

    async def _finish_execution(
        self,
        execution_id: str,
        *,
        graph_execution_time_ms: float,
        status: str,
    ) -> None:
        metrics = self._store.get(execution_id)
        if metrics is None:
            return
        metrics.graph_execution_time_ms = graph_execution_time_ms
        metrics.finished_at = datetime.now(UTC)
        metrics.status = status

    async def _append_node(
        self,
        execution_id: str,
        *,
        node_id: str,
        sequence: int,
        latency_ms: float,
        status: str,
    ) -> None:
        metrics = self._store.get(execution_id)
        if metrics is None:
            return
        metrics.nodes.append(
            NodeMetric(
                node_id=node_id,
                sequence=sequence,
                latency_ms=latency_ms,
                status=status,
            ),
        )

    async def _append_tool(
        self,
        execution_id: str,
        *,
        call_id: str,
        tool_name: str,
        latency_ms: float,
        success: bool,
        attempt: int,
        max_attempts: int,
        is_fallback: bool,
        error: str | None,
    ) -> None:
        metrics = self._store.get(execution_id)
        if metrics is None:
            return
        is_retry = attempt > 1
        metrics.tools.append(
            ToolMetric(
                call_id=call_id,
                tool_name=tool_name,
                latency_ms=latency_ms,
                success=success,
                attempt=attempt,
                max_attempts=max_attempts,
                is_retry=is_retry,
                is_fallback=is_fallback,
                error=error,
            ),
        )
        if is_retry:
            metrics.retry_count += 1

    async def _append_llm(
        self,
        execution_id: str,
        *,
        caller: str,
        latency_ms: float,
        usage: LLMUsage,
        estimated_cost_usd: float,
        model: str | None,
        provider: str | None = None,
    ) -> None:
        metrics = self._store.get(execution_id)
        if metrics is None:
            return
        metrics.llm_calls.append(
            LLMMetric(
                caller=caller,
                latency_ms=latency_ms,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                estimated_cost_usd=estimated_cost_usd,
                estimated=usage.estimated,
                model=model,
                provider=provider,
            ),
        )
