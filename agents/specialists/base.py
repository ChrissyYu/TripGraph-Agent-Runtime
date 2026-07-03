"""Base class for domain-specific specialist agents."""

from abc import abstractmethod
from collections.abc import AsyncIterator

from agents.base import BaseAgent
from schemas.agent import AgentTask, AgentTaskResult
from schemas.streaming import StreamEvent, StreamEventType


class BaseSpecialistAgent(BaseAgent):
    """Specialist agents handle focused sub-tasks delegated by the manager."""

    specialty: str

    @abstractmethod
    async def run(self, task: AgentTask) -> AgentTaskResult:
        ...

    async def stream(self, task: AgentTask) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(
            event=StreamEventType.START,
            session_id=task.session_id,
            data={"agent": self.name, "task_id": task.task_id},
        )

        result = await self.run(task)

        yield StreamEvent(
            event=StreamEventType.TOKEN,
            session_id=task.session_id,
            data={"content": result.output},
        )
