"""In-process short-term conversation memory."""

from collections import defaultdict, deque

from config.settings import Settings, get_settings
from memory.base import MemoryStore
from schemas.memory import MemoryEntry, MemoryQuery, MemoryScope


class ShortTermMemory(MemoryStore):
    """Session-scoped in-memory store with bounded message history."""

    scope = MemoryScope.SHORT_TERM

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._store: dict[str, deque[MemoryEntry]] = defaultdict(
            lambda: deque(maxlen=self._settings.short_term_max_messages),
        )

    async def save(self, entry: MemoryEntry) -> None:
        self._store[entry.session_id].append(entry)

    async def get(self, query: MemoryQuery) -> list[MemoryEntry]:
        entries = list(self._store.get(query.session_id, deque()))
        if query.key:
            entries = [e for e in entries if e.key == query.key]
        return entries[-query.limit :]

    async def delete(self, session_id: str, key: str) -> bool:
        bucket = self._store.get(session_id)
        if not bucket:
            return False
        original_len = len(bucket)
        filtered = deque(
            (e for e in bucket if e.key != key),
            maxlen=bucket.maxlen,
        )
        self._store[session_id] = filtered
        return len(filtered) < original_len

    async def clear_session(self, session_id: str) -> None:
        self._store.pop(session_id, None)
