"""File-backed long-term memory store."""

import json
from pathlib import Path

from config.settings import Settings, get_settings
from core.exceptions import MemoryError
from memory.base import MemoryStore
from schemas.memory import MemoryEntry, MemoryQuery, MemoryScope


class LongTermMemory(MemoryStore):
    """Persists memory entries as JSON lines per session."""

    scope = MemoryScope.LONG_TERM

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._root = Path(self._settings.long_term_store_path)
        self._root.mkdir(parents=True, exist_ok=True)

    def _session_file(self, session_id: str) -> Path:
        safe_id = session_id.replace("/", "_")
        return self._root / f"{safe_id}.jsonl"

    async def save(self, entry: MemoryEntry) -> None:
        path = self._session_file(entry.session_id)
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(entry.model_dump_json() + "\n")
        except OSError as exc:
            raise MemoryError(f"Failed to write long-term memory: {exc}") from exc

    async def get(self, query: MemoryQuery) -> list[MemoryEntry]:
        path = self._session_file(query.session_id)
        if not path.exists():
            return []

        entries: list[MemoryEntry] = []
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                entry = MemoryEntry.model_validate_json(line.strip())
                if query.key and entry.key != query.key:
                    continue
                entries.append(entry)

        return entries[-query.limit :]

    async def delete(self, session_id: str, key: str) -> bool:
        entries = await self.get(MemoryQuery(session_id=session_id))
        remaining = [e for e in entries if e.key != key]
        if len(remaining) == len(entries):
            return False

        path = self._session_file(session_id)
        with path.open("w", encoding="utf-8") as fh:
            for entry in remaining:
                fh.write(entry.model_dump_json() + "\n")
        return True

    async def clear_session(self, session_id: str) -> None:
        path = self._session_file(session_id)
        if path.exists():
            path.unlink()
