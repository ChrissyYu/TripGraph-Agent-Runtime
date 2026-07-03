"""Non-blocking execution observer for Phase 5 persistence."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from persistence.async_writer import AsyncWriteQueue
from persistence.context import current_execution_id, current_session_id
from persistence.db.models import (
    ExecutionStatus,
    GraphExecutionRecord,
    NodeExecutionRecord,
    NodeStatus,
    PersistedStateVersion,
    ToolCallRecord,
)
from persistence.stores import (
    ExecutionStore,
    NodeStore,
    SessionStore,
    StateStore,
    ToolStore,
)
from tools.tracing import ToolTraceRecord


@dataclass
class ExecutionContext:
    execution_id: str
    session_id: str
    query: str
    graph_id: str | None
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    node_sequence: int = 0
    node_starts: dict[str, float] = field(default_factory=dict)
    pending_inputs: dict[int, dict[str, Any]] = field(default_factory=dict)


class ExecutionRecorder:
    """Observer that records graph execution without blocking the runtime."""

    def __init__(
        self,
        *,
        execution_store: ExecutionStore,
        node_store: NodeStore,
        tool_store: ToolStore,
        state_store: StateStore,
        session_store: SessionStore,
        writer: AsyncWriteQueue,
        enabled: bool = True,
    ) -> None:
        self._execution_store = execution_store
        self._node_store = node_store
        self._tool_store = tool_store
        self._state_store = state_store
        self._session_store = session_store
        self._writer = writer
        self._enabled = enabled
        self._contexts: dict[str, ExecutionContext] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def begin(
        self,
        *,
        session_id: str,
        query: str,
        graph_id: str | None = None,
    ) -> ExecutionContext:
        execution_id = str(uuid4())
        ctx = ExecutionContext(
            execution_id=execution_id,
            session_id=session_id,
            query=query,
            graph_id=graph_id,
        )
        self._contexts[execution_id] = ctx
        current_execution_id.set(execution_id)
        current_session_id.set(session_id)

        if not self._enabled:
            return ctx

        record = GraphExecutionRecord(
            execution_id=execution_id,
            session_id=session_id,
            query=query,
            start_time=ctx.start_time,
            status=ExecutionStatus.RUNNING,
            graph_id=graph_id,
        )
        self._writer.submit(self._execution_store.insert, record)
        return ctx

    def on_graph_event(self, ctx: ExecutionContext, event: dict[str, Any]) -> None:
        if not self._enabled:
            return

        event_type = event.get("type")
        if event_type == "node_start":
            node_id = event["node_id"]
            sequence = event.get("sequence", ctx.node_sequence)
            ctx.node_starts[node_id] = time.perf_counter()
            state = event.get("state")
            if state is not None:
                ctx.pending_inputs[sequence] = state.snapshot()
        elif event_type == "node_end":
            self._record_node_end(ctx, event)
        elif event_type == "graph_end":
            state = event.get("state")
            if state is not None:
                self._persist_state_versions(ctx, state)

    def finish(
        self,
        ctx: ExecutionContext,
        state: Any,
        *,
        status: ExecutionStatus,
        error_message: str | None = None,
    ) -> None:
        current_execution_id.set(None)
        current_session_id.set(None)
        self._contexts.pop(ctx.execution_id, None)

        if not self._enabled:
            return

        execution_graph_json = (
            state.execution_graph.to_dag_json()
            if getattr(state, "execution_graph", None)
            else None
        )
        final_result = getattr(state, "final_result", None)
        self._writer.submit(
            self._execution_store.update_completion,
            ctx.execution_id,
            status=status,
            end_time=datetime.now(UTC),
            final_result=final_result,
            execution_graph_json=execution_graph_json,
            error_message=error_message,
        )
        self._persist_state_versions(ctx, state)
        snapshot = state.api_snapshot() if hasattr(state, "api_snapshot") else {}
        self._writer.submit(
            self._session_store.append_execution,
            ctx.session_id,
            ctx.execution_id,
            state_snapshot=snapshot,
        )

    def on_tool_record(self, entry: ToolTraceRecord) -> None:
        if not self._enabled:
            return

        record = ToolCallRecord(
            execution_id=current_execution_id.get(),
            session_id=current_session_id.get(),
            call_id=entry.call_id,
            tool_name=entry.tool_name,
            args=entry.input_args,
            result=entry.output,
            success=entry.success,
            latency_ms=entry.latency_ms,
            error=entry.error,
        )
        self._writer.submit(self._tool_store.insert, record)

    def _record_node_end(self, ctx: ExecutionContext, event: dict[str, Any]) -> None:
        node_id = event["node_id"]
        sequence = event.get("sequence", ctx.node_sequence)
        started = ctx.node_starts.pop(node_id, None)
        latency_ms = (time.perf_counter() - started) * 1000 if started is not None else None
        state = event.get("state")
        input_state = ctx.pending_inputs.pop(sequence, None)
        output_state = state.snapshot() if state is not None else None

        record = NodeExecutionRecord(
            execution_id=ctx.execution_id,
            node_id=node_id,
            sequence=sequence,
            input_state=input_state,
            output_state=output_state,
            input_state_hash=event.get("input_state_hash"),
            output_state_hash=event.get("output_state_hash"),
            latency_ms=latency_ms,
            status=NodeStatus.COMPLETED,
            parallel=event.get("parallel", False),
        )
        ctx.node_sequence = max(ctx.node_sequence, sequence + 1)
        self._writer.submit(self._node_store.insert, record)

        if state is not None:
            self._persist_state_versions(ctx, state)

    def _persist_state_versions(self, ctx: ExecutionContext, state: Any) -> None:
        version_store = getattr(state, "version_store", None)
        if version_store is None:
            return

        for version in version_store.versions:
            persisted = PersistedStateVersion(
                version_id=version.version_id,
                execution_id=ctx.execution_id,
                node_id=version.node_id,
                state_snapshot=version.snapshot,
                parent_version_id=version.parent_version_id,
                state_hash=version.state_hash,
                branch_id=version.branch_id,
                created_at=version.created_at,
            )
            self._writer.submit(self._state_store.insert, persisted)
