"""Export SSE stream events and SQLite persistence records for demo cases."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.bootstrap import bootstrap_runtime
from config.settings import Settings
from graph.runtime.execution_policy import ExecutionPolicy
from observability.context import current_trace_id
from streaming.events import format_sse

CASES = [
    ("case-1", "帮我规划上海3日游并计算预算"),
    ("case-2", "查询上海天气并规划适合的旅行路线"),
    ("case-3", "预算3000，帮我做一个3天旅行计划"),
]

EXPORT_ROOT = Path(__file__).resolve().parents[1] / "data" / "demo_exports"


def _dump_sqlite_raw(db_path: Path, execution_id: str) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    tables = [
        "graph_executions",
        "node_executions",
        "tool_calls",
        "state_versions",
        "sessions",
    ]
    result: dict = {"execution_id": execution_id, "tables": {}}
    for table in tables:
        if table == "graph_executions":
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE execution_id = ?",
                (execution_id,),
            ).fetchall()
        elif table == "sessions":
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        elif table == "state_versions":
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE execution_id = ? ORDER BY created_at",
                (execution_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE execution_id = ? ORDER BY rowid",
                (execution_id,),
            ).fetchall()
        result["tables"][table] = [dict(row) for row in rows]
    conn.close()
    return result


async def main() -> None:
    export_dir = EXPORT_ROOT / datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    export_dir.mkdir(parents=True, exist_ok=True)
    db_path = export_dir / "executions.db"

    settings = Settings(
        persistence_enabled=True,
        persistence_db_path=str(db_path),
        metrics_enabled=True,
        plan_execution_critic_enabled=True,
        plan_critic_replan_enabled=True,
    )
    (
        _registry,
        _memory,
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

    manifest: dict = {
        "exported_at": datetime.now(UTC).isoformat(),
        "db_path": str(db_path),
        "cases": [],
    }

    for session_id, query in CASES:
        case_dir = export_dir / session_id
        case_dir.mkdir(parents=True, exist_ok=True)

        trace_token = current_trace_id.set(f"trace-{session_id}")
        sse_frames: list[str] = []
        sse_events: list[dict] = []

        try:
            async for event in graph_runner.stream(
                query,
                session_id=session_id,
                policy=ExecutionPolicy(capture_state_snapshots=True),
            ):
                frame = format_sse(event)
                sse_frames.append(frame)
                sse_events.append(
                    {
                        "event": event.event.value,
                        "session_id": event.session_id,
                        "data": event.data,
                    },
                )
        finally:
            current_trace_id.reset(trace_token)

        if observability.collector:
            await observability.collector.drain()
        if persistence.writer:
            await persistence.writer.drain()

        execution_id = None
        for ev in reversed(sse_events):
            if ev["event"] == "done":
                execution_id = ev["data"].get("execution_id")
                break
            if ev["event"] == "start":
                execution_id = ev["data"].get("execution_id") or execution_id

        persisted = None
        if execution_id and persistence.replay_service:
            persisted = await persistence.replay_service.get_execution(execution_id)

        sqlite_raw = (
            _dump_sqlite_raw(db_path, execution_id) if execution_id else {"error": "no execution_id"}
        )

        (case_dir / "sse_raw.sse").write_text("".join(sse_frames), encoding="utf-8")
        (case_dir / "sse_events.json").write_text(
            json.dumps(sse_events, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (case_dir / "persistence_replay.json").write_text(
            json.dumps(persisted, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (case_dir / "sqlite_raw.json").write_text(
            json.dumps(sqlite_raw, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        manifest["cases"].append(
            {
                "session_id": session_id,
                "query": query,
                "execution_id": execution_id,
                "sse_event_count": len(sse_events),
                "sse_file": str(case_dir / "sse_raw.sse"),
                "sse_events_json": str(case_dir / "sse_events.json"),
                "persistence_replay_json": str(case_dir / "persistence_replay.json"),
                "sqlite_raw_json": str(case_dir / "sqlite_raw.json"),
                "sqlite_counts": {
                    table: len(sqlite_raw.get("tables", {}).get(table, []))
                    for table in ("graph_executions", "node_executions", "tool_calls", "state_versions")
                },
            },
        )

        print(f"[OK] {session_id} execution_id={execution_id} sse_events={len(sse_events)}", file=sys.stderr)

    if observability.collector:
        await observability.collector.stop()
    if persistence.writer:
        await persistence.writer.stop()

    (export_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(str(export_dir))


if __name__ == "__main__":
    asyncio.run(main())
