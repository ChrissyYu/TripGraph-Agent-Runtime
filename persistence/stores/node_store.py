"""Node execution persistence store."""

from __future__ import annotations

from typing import Any

from persistence.db.models import NodeExecutionRecord, NodeStatus
from persistence.db.sqlite_client import SQLiteClient
from persistence.serialization import dumps_json, loads_json


class NodeStore:
    def __init__(self, client: SQLiteClient) -> None:
        self._client = client

    async def insert(self, record: NodeExecutionRecord) -> None:
        await self._client.execute(
            """
            INSERT INTO node_executions (
                execution_id, node_id, sequence, input_state_json, output_state_json,
                input_state_hash, output_state_hash, latency_ms, status, parallel
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.execution_id,
                record.node_id,
                record.sequence,
                dumps_json(record.input_state) if record.input_state is not None else None,
                dumps_json(record.output_state) if record.output_state is not None else None,
                record.input_state_hash,
                record.output_state_hash,
                record.latency_ms,
                record.status.value,
                1 if record.parallel else 0,
            ),
        )

    async def list_by_execution(self, execution_id: str) -> list[NodeExecutionRecord]:
        rows = await self._client.fetchall(
            """
            SELECT * FROM node_executions
            WHERE execution_id = ?
            ORDER BY sequence ASC, id ASC
            """,
            (execution_id,),
        )
        return [self._row_to_record(r) for r in rows]

    async def get_node(
        self,
        execution_id: str,
        node_id: str,
    ) -> NodeExecutionRecord | None:
        row = await self._client.fetchone(
            """
            SELECT * FROM node_executions
            WHERE execution_id = ? AND node_id = ?
            ORDER BY sequence DESC, id DESC
            LIMIT 1
            """,
            (execution_id, node_id),
        )
        if row is None:
            return None
        return self._row_to_record(row)

    @staticmethod
    def _row_to_record(row: Any) -> NodeExecutionRecord:
        return NodeExecutionRecord(
            id=row["id"],
            execution_id=row["execution_id"],
            node_id=row["node_id"],
            sequence=row["sequence"],
            input_state=loads_json(row["input_state_json"]),
            output_state=loads_json(row["output_state_json"]),
            input_state_hash=row["input_state_hash"],
            output_state_hash=row["output_state_hash"],
            latency_ms=row["latency_ms"],
            status=NodeStatus(row["status"]),
            parallel=bool(row["parallel"]),
        )
