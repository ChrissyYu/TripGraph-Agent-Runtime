"""Tool policy trace recording (Phase 9C)."""

from __future__ import annotations

from typing import Any

from tools.policy.models import ToolPolicyDecision, ToolPolicyTraceEntry


def _log_json(*args, **kwargs) -> None:
    from observability.logging.json_logger import log_json

    log_json(*args, **kwargs)


class ToolPolicyTracer:
    """Collects policy decisions for state, logs, and metrics."""

    def __init__(self, *, trace_enabled: bool = True) -> None:
        self._trace_enabled = trace_enabled
        self._entries: list[ToolPolicyTraceEntry] = []
        self._counters: dict[str, int] = {
            "tool_policy_decision_count": 0,
            "mcp_selected_count": 0,
            "builtin_selected_count": 0,
            "fallback_count": 0,
        }

    @property
    def entries(self) -> list[ToolPolicyTraceEntry]:
        return list(self._entries)

    @property
    def counters(self) -> dict[str, int]:
        return dict(self._counters)

    def record(
        self,
        decision: ToolPolicyDecision,
        *,
        execution_id: str | None = None,
        trace_id: str | None = None,
        session_id: str | None = None,
        step_id: int | None = None,
        task: str | None = None,
        query: str | None = None,
    ) -> ToolPolicyTraceEntry:
        entry = ToolPolicyTraceEntry(
            **decision.model_dump(),
            execution_id=execution_id,
            trace_id=trace_id,
            session_id=session_id,
            step_id=step_id,
            task=task,
            query=query,
        )
        if not self._trace_enabled:
            return entry

        self._entries.append(entry)
        self._counters["tool_policy_decision_count"] += 1
        provider = decision.selected_provider.value
        if provider == "mcp":
            self._counters["mcp_selected_count"] += 1
        elif provider == "builtin":
            self._counters["builtin_selected_count"] += 1
        if decision.fallback_used:
            self._counters["fallback_count"] += 1

        fields = entry.model_dump_json_safe()
        for key in ("execution_id", "trace_id", "session_id", "step_id", "task", "query"):
            fields.pop(key, None)
        _log_json(
            "tools.policy",
            "tool_policy_decision",
            execution_id=execution_id,
            trace_id=trace_id,
            step_id=step_id,
            task=task,
            query=query,
            **fields,
        )
        return entry

    def record_fallback(
        self,
        entry: ToolPolicyTraceEntry,
        *,
        fallback_tool: str,
        failure_reason: str,
        recovery_action: str,
    ) -> ToolPolicyTraceEntry:
        updated = entry.model_copy(
            update={
                "fallback_used": True,
                "fallback_tool": fallback_tool,
                "failure_reason": failure_reason,
                "selected_tool": fallback_tool,
                "selected_provider": entry.selected_provider,
                "reason": f"{entry.reason}; fallback after failure ({recovery_action})",
            },
        )
        if self._trace_enabled and self._entries:
            self._entries[-1] = updated
            self._counters["fallback_count"] += 1
            _log_json(
                "tools.policy",
                "tool_policy_fallback",
                execution_id=entry.execution_id,
                trace_id=entry.trace_id,
                original_tool=entry.original_tool_hint,
                failed_tool=entry.selected_tool,
                fallback_tool=fallback_tool,
                recovery_action=recovery_action,
                failure_reason=failure_reason,
            )
        return updated

    def to_observations_list(self) -> list[dict[str, Any]]:
        return [entry.model_dump_json_safe() for entry in self._entries]

    def clear(self) -> None:
        self._entries.clear()
        for key in self._counters:
            self._counters[key] = 0
