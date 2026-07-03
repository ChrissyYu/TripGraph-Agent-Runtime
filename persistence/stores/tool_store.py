"""Tool call persistence store."""

from __future__ import annotations

from typing import Any

from persistence.db.models import ToolCallRecord
from persistence.db.sqlite_client import SQLiteClient
from persistence.serialization import dumps_json, loads_json


class ToolStore:
    def __init__(self, client: SQLiteClient) -> None:
        self._client = client

    async def insert(self, record: ToolCallRecord) -> None:
        await self._client.execute(
            """
            INSERT INTO tool_calls (
                execution_id, session_id, call_id, tool_name, args_json,
                result_json, success, latency_ms, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.execution_id,
                record.session_id,
                record.call_id,
                record.tool_name,
                dumps_json(record.args),
                dumps_json(record.result),
                1 if record.success else 0,
                record.latency_ms,
                record.error,
            ),
        )

    async def list_by_execution(self, execution_id: str) -> list[ToolCallRecord]:
        rows = await self._client.fetchall(
            """
            SELECT * FROM tool_calls
            WHERE execution_id = ?
            ORDER BY id ASC
            """,
            (execution_id,),
        )
        return [self._row_to_record(r) for r in rows]

    async def list_by_session(self, session_id: str) -> list[ToolCallRecord]:
        rows = await self._client.fetchall(
            """
            SELECT * FROM tool_calls
            WHERE session_id = ?
            ORDER BY id ASC
            """,
            (session_id,),
        )
        return [self._row_to_record(r) for r in rows]

    @staticmethod
    def _row_to_record(row: Any) -> ToolCallRecord:
        return ToolCallRecord(
            id=row["id"],
            execution_id=row["execution_id"],
            session_id=row["session_id"],
            call_id=row["call_id"],
            tool_name=row["tool_name"],
            args=loads_json(row["args_json"]) or {},
            result=loads_json(row["result_json"]),
            success=bool(row["success"]),
            latency_ms=row["latency_ms"],
            error=row["error"],
        )
