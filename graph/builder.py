"""LangGraph workflow builder interface."""

from abc import ABC, abstractmethod
from typing import Any, Protocol


class CompiledGraph(Protocol):
    """Protocol mirroring LangGraph CompiledGraph surface."""

    async def ainvoke(self, input: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        ...

    async def astream(self, input: dict[str, Any], config: dict[str, Any] | None = None):
        ...


class GraphBuilder(ABC):
    """Build and compile LangGraph workflows.

    Implementations should wire manager/specialist/tool nodes into a StateGraph.
    """

    @abstractmethod
    def build(self) -> CompiledGraph:
        """Compile and return the workflow graph."""

    @abstractmethod
    def build_stub(self) -> CompiledGraph:
        """Return a no-op graph for environments without LangGraph runtime."""
