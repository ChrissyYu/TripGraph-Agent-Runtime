"""Graph execution persistence store."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from persistence.db.models import ExecutionStatus, GraphExecutionRecord
from persistence.db.sqlite_client import SQLiteClient
from persistence.serialization import dumps_json, loads_json


class ExecutionStore:
    def __init__(self, client: SQLiteClient) -> None:
        self._client = client

    async def insert(self, record: GraphExecutionRecord) -> None:
        await self._client.execute(
            """
            INSERT INTO graph_executions (
                execution_id, session_id, query, start_time, end_time,
                status, graph_id, final_result, execution_graph_json, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.execution_id,
                record.session_id,
                record.query,
                record.start_time.isoformat(),
                record.end_time.isoformat() if record.end_time else None,
                record.status.value,
                record.graph_id,
                record.final_result,
                dumps_json(record.execution_graph_json) if record.execution_graph_json else None,
                record.error_message,
            ),
        )

    async def update_completion(
        self,
        execution_id: str,
        *,
        status: ExecutionStatus,
        end_time: datetime | None = None,
        final_result: str | None = None,
        execution_graph_json: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        await self._client.execute(
            """
            UPDATE graph_executions
            SET end_time = ?, status = ?, final_result = ?,
                execution_graph_json = ?, error_message = ?
            WHERE execution_id = ?
            """,
            (
                (end_time or datetime.now(UTC)).isoformat(),
                status.value,
                final_result,
                dumps_json(execution_graph_json) if execution_graph_json else None,
                error_message,
                execution_id,
            ),
        )

    async def get(self, execution_id: str) -> GraphExecutionRecord | None:
        row = await self._client.fetchone(
            "SELECT * FROM graph_executions WHERE execution_id = ?",
            (execution_id,),
        )
        if row is None:
            return None
        return self._row_to_record(row)

    async def list_by_session(self, session_id: str) -> list[GraphExecutionRecord]:
        rows = await self._client.fetchall(
            """
            SELECT * FROM graph_executions
            WHERE session_id = ?
            ORDER BY start_time ASC
            """,
            (session_id,),
        )
        return [self._row_to_record(r) for r in rows]

    @staticmethod
    def _row_to_record(row: Any) -> GraphExecutionRecord:
        return GraphExecutionRecord(
            execution_id=row["execution_id"],
            session_id=row["session_id"],
            query=row["query"],
            start_time=datetime.fromisoformat(row["start_time"]),
            end_time=datetime.fromisoformat(row["end_time"]) if row["end_time"] else None,
            status=ExecutionStatus(row["status"]),
            graph_id=row["graph_id"],
            final_result=row["final_result"],
            execution_graph_json=loads_json(row["execution_graph_json"]),
            error_message=row["error_message"],
        )
