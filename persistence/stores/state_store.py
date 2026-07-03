"""State version persistence store."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from persistence.db.models import PersistedStateVersion
from persistence.db.sqlite_client import SQLiteClient
from persistence.serialization import dumps_json, loads_json


class StateStore:
    def __init__(self, client: SQLiteClient) -> None:
        self._client = client

    async def insert(self, record: PersistedStateVersion) -> None:
        await self._client.execute(
            """
            INSERT OR REPLACE INTO state_versions (
                version_id, execution_id, node_id, state_snapshot_json,
                parent_version_id, state_hash, branch_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.version_id,
                record.execution_id,
                record.node_id,
                dumps_json(record.state_snapshot),
                record.parent_version_id,
                record.state_hash,
                record.branch_id,
                record.created_at.isoformat(),
            ),
        )

    async def list_by_execution(self, execution_id: str) -> list[PersistedStateVersion]:
        rows = await self._client.fetchall(
            """
            SELECT * FROM state_versions
            WHERE execution_id = ?
            ORDER BY created_at ASC
            """,
            (execution_id,),
        )
        return [self._row_to_record(r) for r in rows]

    async def get(self, version_id: str) -> PersistedStateVersion | None:
        row = await self._client.fetchone(
            "SELECT * FROM state_versions WHERE version_id = ?",
            (version_id,),
        )
        if row is None:
            return None
        return self._row_to_record(row)

    async def get_latest_for_execution(self, execution_id: str) -> PersistedStateVersion | None:
        row = await self._client.fetchone(
            """
            SELECT * FROM state_versions
            WHERE execution_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (execution_id,),
        )
        if row is None:
            return None
        return self._row_to_record(row)

    @staticmethod
    def _row_to_record(row: Any) -> PersistedStateVersion:
        return PersistedStateVersion(
            version_id=row["version_id"],
            execution_id=row["execution_id"],
            node_id=row["node_id"],
            state_snapshot=loads_json(row["state_snapshot_json"]) or {},
            parent_version_id=row["parent_version_id"],
            state_hash=row["state_hash"],
            branch_id=row["branch_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
