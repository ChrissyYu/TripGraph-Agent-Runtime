"""SQLite client with thread-offloaded writes."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

from persistence.db.models import SCHEMA_SQL


class SQLiteClient:
    """Lightweight SQLite accessor; blocking calls run via asyncio.to_thread."""

    def __init__(self, db_path: str) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        await asyncio.to_thread(self._execute_sync, sql, params)

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        return await asyncio.to_thread(self._fetchone_sync, sql, params)

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return await asyncio.to_thread(self._fetchall_sync, sql, params)

    def _execute_sync(self, sql: str, params: tuple[Any, ...]) -> None:
        with self._connect() as conn:
            conn.execute(sql, params)
            conn.commit()

    def _fetchone_sync(self, sql: str, params: tuple[Any, ...]) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(sql, params).fetchone()

    def _fetchall_sync(self, sql: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(sql, params).fetchall()
