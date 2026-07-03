"""One-off demo trace runner for Phase 1-8 verification."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from app.bootstrap import bootstrap_runtime
from config.settings import Settings
from graph.runtime.execution_policy import ExecutionPolicy
from observability.context import current_trace_id
from observability.profile import ExecutionProfileService

CASES = [
    ("case-1", "帮我规划上海3日游并计算预算"),
    ("case-2", "查询上海天气并规划适合的旅行路线"),
    ("case-3", "预算3000，帮我做一个3天旅行计划"),
]


async def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="demo_trace_"))
    settings = Settings(
        persistence_enabled=True,
        persistence_db_path=str(tmp / "executions.db"),
        metrics_enabled=True,
        enable_json_log=False,
        plan_execution_critic_enabled=True,
        plan_critic_replan_enabled=True,
    )
    (
        _registry,
        _memory_store,
        *_,
        graph_runner,
        persistence,
        observability,
        _eval,
    ) = bootstrap_runtime(settings)

    if persistence.writer:
        await persistence.writer.start()
    if observability.collector:
        await observability.collector.start()

    profile_service = ExecutionProfileService(observability.store)  # type: ignore[arg-type]
    results = []

    for session_id, query in CASES:
        trace_token = current_trace_id.set(f"trace-{session_id}")
        try:
            response = await graph_runner.invoke(
                query,
                session_id=session_id,
                policy=ExecutionPolicy(capture_state_snapshots=True),
            )
        finally:
            current_trace_id.reset(trace_token)

        if observability.collector:
            await observability.collector.drain()

        execution_id = response.execution_id
        profile = profile_service.get_profile(execution_id) if execution_id else None
        persisted = None
        if execution_id and persistence.replay_service:
            persisted = await persistence.replay_service.get_execution(execution_id)

        node_events = []
        step = 0
        for entry in response.graph_trace:
            if entry.event == "node_start":
                step += 1
                node_events.append(
                    {"step": step, "type": "node_start", "node_id": entry.node_id, "data": entry.data},
                )
            elif entry.event == "node_end":
                node_events.append(
                    {"step": step, "type": "node_end", "node_id": entry.node_id, "data": entry.data},
                )

        edges = []
        if response.execution_graph:
            edges = list(response.execution_graph.get("edges", []))

        results.append(
            {
                "session_id": session_id,
                "query": query,
                "execution_id": execution_id,
                "trace_id": profile.get("trace_id") if profile else None,
                "node_timeline": [t.model_dump(mode="json") for t in response.node_timeline],
                "node_events": node_events,
                "graph_edges": edges,
                "plan": response.plan.model_dump(mode="json") if response.plan else None,
                "execution_trace": [t.model_dump(mode="json") for t in response.execution_trace],
                "execution_critique": (
                    response.execution_critique.model_dump(mode="json") if response.execution_critique else None
                ),
                "replan_history": [r.model_dump(mode="json") for r in response.replan_history],
                "state_summary": response.state_summary,
                "profile": profile,
                "persisted_tool_calls": persisted.get("tool_calls") if persisted else [],
                "persisted_nodes": [
                    {"node_id": n["node_id"], "sequence": n["sequence"]}
                    for n in (persisted.get("nodes") or [])
                ]
                if persisted
                else [],
                "final_result": response.final_result,
            },
        )

    if observability.collector:
        await observability.collector.stop()
    if persistence.writer:
        await persistence.writer.stop()

    json.dump(results, sys.stdout, ensure_ascii=False, indent=2, default=str)


if __name__ == "__main__":
    asyncio.run(main())
