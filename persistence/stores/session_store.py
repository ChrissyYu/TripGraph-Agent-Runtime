"""Session persistence store."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from persistence.db.models import SessionRecord
from persistence.db.sqlite_client import SQLiteClient
from persistence.serialization import dumps_json, loads_json


class SessionStore:
    def __init__(self, client: SQLiteClient) -> None:
        self._client = client

    async def upsert(self, record: SessionRecord) -> None:
        await self._client.execute(
            """
            INSERT INTO sessions (
                session_id, history_json, last_execution_id,
                last_state_snapshot_json, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                history_json = excluded.history_json,
                last_execution_id = excluded.last_execution_id,
                last_state_snapshot_json = excluded.last_state_snapshot_json,
                updated_at = excluded.updated_at
            """,
            (
                record.session_id,
                dumps_json(record.history),
                record.last_execution_id,
                dumps_json(record.last_state_snapshot) if record.last_state_snapshot else None,
                record.updated_at.isoformat(),
            ),
        )

    async def get(self, session_id: str) -> SessionRecord | None:
        row = await self._client.fetchone(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        if row is None:
            return None
        return self._row_to_record(row)

    async def append_execution(
        self,
        session_id: str,
        execution_id: str,
        *,
        state_snapshot: dict[str, Any] | None = None,
    ) -> SessionRecord:
        existing = await self.get(session_id)
        history = list(existing.history) if existing else []
        if execution_id not in history:
            history.append(execution_id)
        record = SessionRecord(
            session_id=session_id,
            history=history,
            last_execution_id=execution_id,
            last_state_snapshot=state_snapshot or (existing.last_state_snapshot if existing else None),
            updated_at=datetime.now(UTC),
        )
        await self.upsert(record)
        return record

    @staticmethod
    def _row_to_record(row: Any) -> SessionRecord:
        return SessionRecord(
            session_id=row["session_id"],
            history=loads_json(row["history_json"]) or [],
            last_execution_id=row["last_execution_id"],
            last_state_snapshot=loads_json(row["last_state_snapshot_json"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
