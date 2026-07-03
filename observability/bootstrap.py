"""Observability bootstrap and wiring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from config.settings import Settings
from observability.llm.instrumented import InstrumentedLLMClient
from observability.metrics.collector import MetricsCollector
from observability.metrics.store import MetricsStore
from observability.observer import MetricsObserver
from observability.profile import ExecutionProfileService
from tools.tracing import ToolTraceRecord, ToolTracer

if TYPE_CHECKING:
    from graph.runtime.runner import GraphRuntimeRunner
    from tools.executor import ToolExecutor


@dataclass
class ObservabilityBundle:
    enabled: bool
    store: MetricsStore | None = None
    collector: MetricsCollector | None = None
    observer: MetricsObserver | None = None
    profile_service: ExecutionProfileService | None = None


def build_observability(settings: Settings) -> ObservabilityBundle:
    if not settings.metrics_enabled:
        return ObservabilityBundle(enabled=False)

    store = MetricsStore()
    collector = MetricsCollector(store, settings=settings, enabled=True)
    observer = MetricsObserver(collector, enabled=True)
    profile_service = ExecutionProfileService(store)
    return ObservabilityBundle(
        enabled=True,
        store=store,
        collector=collector,
        observer=observer,
        profile_service=profile_service,
    )


def wrap_llm_client(inner, bundle: ObservabilityBundle, *, settings: Settings):
    if not bundle.enabled or bundle.collector is None:
        return inner
    return InstrumentedLLMClient(inner, bundle.collector, settings=settings)


def wire_tool_tracer(
    tool_executor: ToolExecutor,
    *,
    callbacks: list[Callable[[ToolTraceRecord], None]],
) -> None:
    if not callbacks:
        return

    def _chain(record: ToolTraceRecord) -> None:
        for callback in callbacks:
            callback(record)

    tool_executor._tracer = ToolTracer(on_record=_chain)


def bind_runner_metrics(bundle: ObservabilityBundle, runner: GraphRuntimeRunner) -> None:
    return None
