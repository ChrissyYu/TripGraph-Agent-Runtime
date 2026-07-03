"""Unified memory facade combining short-term and long-term stores."""

from memory.base import MemoryStore
from memory.episodic import EpisodicMemory
from memory.long_term import LongTermMemory
from memory.short_term import ShortTermMemory
from schemas.memory import MemoryEntry, MemoryQuery, MemoryScope


class CompositeMemory:
    """Routes memory operations to the appropriate backend by scope."""

    def __init__(
        self,
        short_term: ShortTermMemory | None = None,
        long_term: LongTermMemory | None = None,
        episodic: EpisodicMemory | None = None,
    ) -> None:
        self.short_term = short_term or ShortTermMemory()
        self.long_term = long_term or LongTermMemory()
        self.episodic = episodic or EpisodicMemory()

    def _resolve(self, scope: MemoryScope) -> MemoryStore:
        if scope == MemoryScope.SHORT_TERM:
            return self.short_term
        if scope == MemoryScope.EPISODIC:
            return self.episodic
        return self.long_term

    async def save(self, entry: MemoryEntry) -> None:
        await self._resolve(entry.scope).save(entry)

    async def get(self, query: MemoryQuery) -> list[MemoryEntry]:
        if query.scope:
            return await self._resolve(query.scope).get(query)

        short = await self.short_term.get(query)
        long = await self.long_term.get(query)
        episodic = await self.episodic.get(query)
        combined = short + long + episodic
        return combined[-query.limit :]

    async def delete(self, session_id: str, key: str, scope: MemoryScope) -> bool:
        return await self._resolve(scope).delete(session_id, key)

    async def clear_session(self, session_id: str) -> None:
        await self.short_term.clear_session(session_id)
        await self.long_term.clear_session(session_id)
        await self.episodic.clear_session(session_id)
