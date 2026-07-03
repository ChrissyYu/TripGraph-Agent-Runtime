"""Tests for memory stores."""

import pytest

from schemas.memory import MemoryEntry, MemoryQuery, MemoryScope


@pytest.mark.asyncio
async def test_short_term_save_and_get(memory_store) -> None:
    entry = MemoryEntry(
        session_id="sess-1",
        key="msg",
        content="hello",
        scope=MemoryScope.SHORT_TERM,
    )
    await memory_store.save(entry)

    results = await memory_store.get(
        MemoryQuery(session_id="sess-1", scope=MemoryScope.SHORT_TERM),
    )
    assert len(results) == 1
    assert results[0].content == "hello"


@pytest.mark.asyncio
async def test_long_term_persistence(memory_store) -> None:
    entry = MemoryEntry(
        session_id="sess-2",
        key="fact",
        content="user prefers window seats",
        scope=MemoryScope.LONG_TERM,
    )
    await memory_store.save(entry)

    results = await memory_store.get(
        MemoryQuery(session_id="sess-2", scope=MemoryScope.LONG_TERM),
    )
    assert results[0].content == "user prefers window seats"
