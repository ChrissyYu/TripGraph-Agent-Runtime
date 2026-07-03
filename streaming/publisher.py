"""Bridge agent streams to SSE consumers."""

from collections.abc import AsyncIterator

from agents.manager import ManagerAgent
from schemas.agent import AgentTask
from schemas.streaming import StreamEvent
from streaming.sse import stream_with_heartbeat


class StreamPublisher:
    """Publishes manager agent events as SSE frames."""

    def __init__(self, manager: ManagerAgent) -> None:
        self._manager = manager

    async def publish(self, task: AgentTask) -> AsyncIterator[str]:
        events = self._manager.stream(task)
        async for frame in stream_with_heartbeat(events):
            yield frame
