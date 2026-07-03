"""Tool execution tracing: records, export, and debug tree rendering."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ToolTraceRecord(BaseModel):
    """Single tool invocation trace entry."""

    call_id: str
    tool_name: str
    input_args: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    latency_ms: float
    success: bool
    error: str | None = None
    parent_id: str | None = None
    attempt: int = 1
    max_attempts: int = 1
    is_fallback: bool = False
    original_tool: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "input_args": self.input_args,
            "output": self.output,
            "latency_ms": round(self.latency_ms, 3),
            "success": self.success,
            "error": self.error,
            "parent_id": self.parent_id,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "is_fallback": self.is_fallback,
            "original_tool": self.original_tool,
            "timestamp": self.timestamp.isoformat(),
        }


class ToolTraceLog(BaseModel):
    """Aggregated trace log for a session."""

    session_id: str
    records: list[ToolTraceRecord] = Field(default_factory=list)

    def export_json(self, *, indent: int = 2) -> str:
        payload = {
            "session_id": self.session_id,
            "record_count": len(self.records),
            "records": [r.to_log_dict() for r in self.records],
        }
        return json.dumps(payload, ensure_ascii=False, indent=indent)

    def print_trace_tree(self) -> str:
        """Render a human-readable trace tree (also returned as string)."""
        lines = [f"ToolTrace session={self.session_id}"]

        roots = [r for r in self.records if r.parent_id is None]
        if not roots:
            roots = self.records

        for index, root in enumerate(roots):
            is_last_root = index == len(roots) - 1
            lines.extend(_render_node(root, self.records, prefix="", is_last=is_last_root))

        tree = "\n".join(lines)
        print(tree)
        return tree


def _render_node(
    node: ToolTraceRecord,
    all_records: list[ToolTraceRecord],
    *,
    prefix: str,
    is_last: bool,
) -> list[str]:
    connector = "└─ " if is_last else "├─ "
    status = "✓" if node.success else "✗"
    label = (
        f"{node.tool_name} {status} "
        f"[{node.latency_ms:.2f}ms] "
        f"attempt={node.attempt}/{node.max_attempts}"
    )
    if node.is_fallback:
        label += f" fallback_from={node.original_tool!r}"
    label += f" args={json.dumps(node.input_args, ensure_ascii=False)}"
    if not node.success and node.error:
        label += f" error={node.error!r}"

    lines = [f"{prefix}{connector}{label}"]

    children = [r for r in all_records if r.parent_id == node.call_id]
    child_prefix = prefix + ("   " if is_last else "│  ")

    for index, child in enumerate(children):
        lines.extend(
            _render_node(
                child,
                all_records,
                prefix=child_prefix,
                is_last=index == len(children) - 1,
            ),
        )

    return lines


class ToolTracer:
    """Collects tool execution traces for a session."""

    def __init__(
        self,
        *,
        session_id: str | None = None,
        debug: bool = False,
        on_record: Callable[[ToolTraceRecord], None] | None = None,
    ) -> None:
        self._session_id = session_id or str(uuid4())
        self._debug = debug
        self._on_record = on_record
        self._records: list[ToolTraceRecord] = []

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def debug(self) -> bool:
        return self._debug

    @property
    def records(self) -> list[ToolTraceRecord]:
        return list(self._records)

    def record(self, entry: ToolTraceRecord) -> None:
        self._records.append(entry)
        if self._on_record is not None:
            self._on_record(entry)
        if self._debug:
            log = ToolTraceLog(session_id=self._session_id, records=[entry])
            log.print_trace_tree()

    def export_json(self, *, indent: int = 2) -> str:
        return ToolTraceLog(session_id=self._session_id, records=self._records).export_json(
            indent=indent,
        )

    def print_trace_tree(self) -> str:
        return ToolTraceLog(session_id=self._session_id, records=self._records).print_trace_tree()

    def clear(self) -> None:
        self._records.clear()

    def trace_tool_call(
        self,
        *,
        call_id: str,
        tool_name: str,
        input_args: dict[str, Any],
        parent_id: str | None = None,
        attempt: int = 1,
        max_attempts: int = 1,
        is_fallback: bool = False,
        original_tool: str | None = None,
    ) -> _TraceTimer:
        return _TraceTimer(
            tracer=self,
            call_id=call_id,
            tool_name=tool_name,
            input_args=input_args,
            parent_id=parent_id,
            attempt=attempt,
            max_attempts=max_attempts,
            is_fallback=is_fallback,
            original_tool=original_tool,
        )


class _TraceTimer:
    """Context manager that measures latency and records a trace on exit."""

    def __init__(
        self,
        *,
        tracer: ToolTracer,
        call_id: str,
        tool_name: str,
        input_args: dict[str, Any],
        parent_id: str | None,
        attempt: int = 1,
        max_attempts: int = 1,
        is_fallback: bool = False,
        original_tool: str | None = None,
    ) -> None:
        self._tracer = tracer
        self._call_id = call_id
        self._tool_name = tool_name
        self._input_args = input_args
        self._parent_id = parent_id
        self._attempt = attempt
        self._max_attempts = max_attempts
        self._is_fallback = is_fallback
        self._original_tool = original_tool
        self._start: float = 0.0
        self.output: Any = None
        self.success: bool = True
        self.error: str | None = None

    def __enter__(self) -> _TraceTimer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, _tb) -> None:
        latency_ms = (time.perf_counter() - self._start) * 1000
        if exc is not None:
            self.success = False
            self.error = str(exc)

        self._tracer.record(
            ToolTraceRecord(
                call_id=self._call_id,
                tool_name=self._tool_name,
                input_args=self._input_args,
                output=self.output,
                latency_ms=latency_ms,
                success=self.success,
                error=self.error,
                parent_id=self._parent_id,
                attempt=self._attempt,
                max_attempts=self._max_attempts,
                is_fallback=self._is_fallback,
                original_tool=self._original_tool,
            ),
        )

    def set_result(self, *, output: Any, success: bool = True, error: str | None = None) -> None:
        self.output = output
        self.success = success
        self.error = error
