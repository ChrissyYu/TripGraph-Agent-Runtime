"""Abstract memory store interface."""

from abc import ABC, abstractmethod

from schemas.memory import MemoryEntry, MemoryQuery, MemoryScope


class MemoryStore(ABC):
    """Contract for short-term and long-term memory backends."""

    scope: MemoryScope

    @abstractmethod
    async def save(self, entry: MemoryEntry) -> None:
        ...

    @abstractmethod
    async def get(self, query: MemoryQuery) -> list[MemoryEntry]:
        ...

    @abstractmethod
    async def delete(self, session_id: str, key: str) -> bool:
        ...

    @abstractmethod
    async def clear_session(self, session_id: str) -> None:
        ...
