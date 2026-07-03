"""Manager agent: routes tasks to specialist agents."""

from collections.abc import AsyncIterator
from uuid import uuid4

from agents.base import BaseAgent
from agents.specialists.base import BaseSpecialistAgent
from core.logging import get_logger
from schemas.agent import AgentTask, AgentTaskResult
from schemas.streaming import StreamEvent, StreamEventType
from tools.registry import ToolRegistry

logger = get_logger(__name__)


class ManagerAgent(BaseAgent):
    """Orchestrates specialist agents and aggregates results."""

    name = "manager"
    description = "Routes user requests to the appropriate specialist agent."

    def __init__(
        self,
        tool_registry: ToolRegistry,
        specialists: dict[str, BaseSpecialistAgent] | None = None,
    ) -> None:
        super().__init__(tool_registry)
        self._specialists: dict[str, BaseSpecialistAgent] = specialists or {}

    def register_specialist(self, specialist: BaseSpecialistAgent) -> None:
        self._specialists[specialist.name] = specialist
        logger.info("Registered specialist: %s", specialist.name)

    def resolve_specialist(self, task: AgentTask) -> BaseSpecialistAgent:
        if task.target_specialist and task.target_specialist in self._specialists:
            return self._specialists[task.target_specialist]

        if len(self._specialists) == 1:
            return next(iter(self._specialists.values()))

        # Default routing: first registered specialist (replace with LLM routing later)
        if self._specialists:
            return next(iter(self._specialists.values()))

        raise ValueError("No specialist agents registered")

    async def run(self, task: AgentTask) -> AgentTaskResult:
        specialist = self.resolve_specialist(task)
        logger.info("Manager delegating task %s to %s", task.task_id, specialist.name)
        result = await specialist.run(task)
        result.specialist_used = specialist.name
        return result

    async def stream(self, task: AgentTask) -> AsyncIterator[StreamEvent]:
        specialist = self.resolve_specialist(task)

        yield StreamEvent(
            event=StreamEventType.AGENT_HANDOFF,
            session_id=task.session_id,
            data={"from": self.name, "to": specialist.name, "task_id": task.task_id},
        )

        async for event in specialist.stream(task):
            yield event

        yield StreamEvent(
            event=StreamEventType.DONE,
            session_id=task.session_id,
            data={"task_id": task.task_id, "specialist": specialist.name},
        )

    def create_task(self, session_id: str, query: str, **context: object) -> AgentTask:
        return AgentTask(
            task_id=str(uuid4()),
            session_id=session_id,
            query=query,
            context=dict(context),
        )
