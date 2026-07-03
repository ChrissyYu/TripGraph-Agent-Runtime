"""Abstract base for all agents."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from schemas.agent import AgentMessage, AgentTask, AgentTaskResult
from schemas.streaming import StreamEvent
from tools.registry import ToolRegistry


class BaseAgent(ABC):
    """Common contract for manager and specialist agents."""

    name: str
    description: str

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._tools = tool_registry

    @abstractmethod
    async def run(self, task: AgentTask) -> AgentTaskResult:
        """Execute a task and return the final result."""

    @abstractmethod
    async def stream(self, task: AgentTask) -> AsyncIterator[StreamEvent]:
        """Stream incremental events for a task."""
        yield  # pragma: no cover

    @property
    def available_tools(self) -> list[str]:
        return self._tools.list_names()

    def build_system_prompt(self) -> str:
        return f"You are {self.name}. {self.description}"

    def format_history(self, messages: list[AgentMessage]) -> str:
        return "\n".join(f"{m.role}: {m.content}" for m in messages)
