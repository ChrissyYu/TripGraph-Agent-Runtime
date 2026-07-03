"""Execution profile report builder."""

from __future__ import annotations

from typing import Any

from observability.metrics.models import ExecutionMetrics
from observability.metrics.store import MetricsStore


class ExecutionProfileService:
    """Build execution profile reports from aggregated metrics."""

    def __init__(self, store: MetricsStore) -> None:
        self._store = store

    def get_profile(self, execution_id: str) -> dict[str, Any] | None:
        metrics = self._store.get(execution_id)
        if metrics is None:
            return None
        return self.build_profile(metrics)

    @staticmethod
    def build_profile(metrics: ExecutionMetrics) -> dict[str, Any]:
        node_breakdown = _aggregate_nodes(metrics)
        tool_breakdown = _aggregate_tools(metrics)
        cost_breakdown = _aggregate_costs(metrics)
        llm_breakdown = _aggregate_llm(metrics)
        bottleneck = _find_bottleneck_node(metrics)

        return {
            "execution_id": metrics.execution_id,
            "session_id": metrics.session_id,
            "trace_id": metrics.trace_id,
            "status": metrics.status,
            "total_latency_ms": metrics.graph_execution_time_ms or 0.0,
            "graph_execution_time_ms": metrics.graph_execution_time_ms,
            "node_execution_count": len(metrics.nodes),
            "tool_call_count": len(metrics.tools),
            "llm_call_count": len(metrics.llm_calls),
            "retry_count": metrics.retry_count,
            "tool_success_rate": round(metrics.tool_success_rate, 4),
            "node_breakdown": node_breakdown,
            "tool_breakdown": tool_breakdown,
            "llm_breakdown": llm_breakdown,
            "bottleneck_node": bottleneck,
            "cost_breakdown": cost_breakdown,
            "total_tokens": metrics.total_llm_tokens,
            "total_estimated_cost_usd": round(metrics.total_estimated_cost_usd, 6),
        }


def _aggregate_nodes(metrics: ExecutionMetrics) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for node in metrics.nodes:
        bucket = grouped.setdefault(
            node.node_id,
            {
                "node_id": node.node_id,
                "count": 0,
                "total_latency_ms": 0.0,
                "max_latency_ms": 0.0,
                "avg_latency_ms": 0.0,
            },
        )
        bucket["count"] += 1
        bucket["total_latency_ms"] += node.latency_ms
        bucket["max_latency_ms"] = max(bucket["max_latency_ms"], node.latency_ms)

    result = []
    for bucket in grouped.values():
        bucket["avg_latency_ms"] = round(bucket["total_latency_ms"] / bucket["count"], 3)
        bucket["total_latency_ms"] = round(bucket["total_latency_ms"], 3)
        bucket["max_latency_ms"] = round(bucket["max_latency_ms"], 3)
        result.append(bucket)
    return sorted(result, key=lambda item: item["total_latency_ms"], reverse=True)


def _aggregate_tools(metrics: ExecutionMetrics) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for tool in metrics.tools:
        bucket = grouped.setdefault(
            tool.tool_name,
            {
                "tool_name": tool.tool_name,
                "count": 0,
                "success_count": 0,
                "total_latency_ms": 0.0,
                "retry_count": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
            },
        )
        bucket["count"] += 1
        bucket["total_latency_ms"] += tool.latency_ms
        if tool.success:
            bucket["success_count"] += 1
        if tool.is_retry:
            bucket["retry_count"] += 1

    result = []
    for bucket in grouped.values():
        bucket["success_rate"] = round(bucket["success_count"] / bucket["count"], 4)
        bucket["avg_latency_ms"] = round(bucket["total_latency_ms"] / bucket["count"], 3)
        bucket["total_latency_ms"] = round(bucket["total_latency_ms"], 3)
        result.append(bucket)
    return sorted(result, key=lambda item: item["total_latency_ms"], reverse=True)


def _aggregate_llm(metrics: ExecutionMetrics) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for call in metrics.llm_calls:
        bucket = grouped.setdefault(
            call.caller,
            {
                "caller": call.caller,
                "count": 0,
                "total_latency_ms": 0.0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
                "avg_latency_ms": 0.0,
                "model": call.model,
                "provider": call.provider,
            },
        )
        bucket["count"] += 1
        bucket["total_latency_ms"] += call.latency_ms
        bucket["prompt_tokens"] += call.prompt_tokens
        bucket["completion_tokens"] += call.completion_tokens
        bucket["total_tokens"] += call.total_tokens
        bucket["estimated_cost_usd"] += call.estimated_cost_usd

    result = []
    for bucket in grouped.values():
        bucket["avg_latency_ms"] = round(bucket["total_latency_ms"] / bucket["count"], 3)
        bucket["total_latency_ms"] = round(bucket["total_latency_ms"], 3)
        bucket["estimated_cost_usd"] = round(bucket["estimated_cost_usd"], 6)
        result.append(bucket)
    return sorted(result, key=lambda item: item["total_latency_ms"], reverse=True)


def _aggregate_costs(metrics: ExecutionMetrics) -> dict[str, Any]:
    by_caller = _aggregate_llm(metrics)
    return {
        "by_caller": by_caller,
        "prompt_tokens": sum(call.prompt_tokens for call in metrics.llm_calls),
        "completion_tokens": sum(call.completion_tokens for call in metrics.llm_calls),
        "total_tokens": metrics.total_llm_tokens,
        "total_estimated_cost_usd": round(metrics.total_estimated_cost_usd, 6),
    }


def _find_bottleneck_node(metrics: ExecutionMetrics) -> dict[str, Any] | None:
    if not metrics.nodes:
        return None
    slowest = max(metrics.nodes, key=lambda node: node.latency_ms)
    return {
        "node_id": slowest.node_id,
        "sequence": slowest.sequence,
        "latency_ms": round(slowest.latency_ms, 3),
    }
