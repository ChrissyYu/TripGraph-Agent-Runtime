"""Tests for multi-agent orchestration."""

import pytest

from schemas.agent import AgentTask


@pytest.mark.asyncio
async def test_manager_delegates_to_specialist(manager_agent) -> None:
    task = AgentTask(task_id="t-1", session_id="s-1", query="plan a trip")
    result = await manager_agent.run(task)

    assert result.specialist_used == "example_specialist"
    assert "plan a trip" in result.output


@pytest.mark.asyncio
async def test_manager_stream_events(manager_agent) -> None:
    task = AgentTask(task_id="t-2", session_id="s-1", query="hello")
    events = [event async for event in manager_agent.stream(task)]

    event_types = [e.event.value for e in events]
    assert "agent_handoff" in event_types
    assert "done" in event_types
