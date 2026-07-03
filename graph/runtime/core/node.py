"""Graph node abstractions."""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol

from graph.runtime.agent_state import AgentState

NodeFn = Callable[[AgentState], Awaitable[AgentState]]


class GraphNode(Protocol):
    """Execution unit: input state, output updated state."""

    id: str

    async def __call__(self, state: AgentState) -> AgentState: ...
