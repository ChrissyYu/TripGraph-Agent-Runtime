"""Episodic memory for graph execution history."""

from memory.short_term import ShortTermMemory
from schemas.memory import MemoryScope


class EpisodicMemory(ShortTermMemory):
    """In-process episodic store keyed by session."""

    scope = MemoryScope.EPISODIC
