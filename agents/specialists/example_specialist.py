"""Placeholder specialist for scaffolding and integration tests."""

from agents.specialists.base import BaseSpecialistAgent
from schemas.agent import AgentTask, AgentTaskResult


class ExampleSpecialistAgent(BaseSpecialistAgent):
    name = "example_specialist"
    description = "Handles example queries during development."
    specialty = "general"

    async def run(self, task: AgentTask) -> AgentTaskResult:
        return AgentTaskResult(
            task_id=task.task_id,
            session_id=task.session_id,
            output=f"[{self.name}] Received: {task.query}",
            specialist_used=self.name,
        )
