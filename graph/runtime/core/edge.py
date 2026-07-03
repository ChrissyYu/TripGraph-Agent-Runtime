"""Graph edge abstractions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from graph.runtime.agent_state import AgentState

RouteFn = Callable[[AgentState], str | None]


class EdgeKind(StrEnum):
    DIRECT = "direct"
    CONDITIONAL = "conditional"
    LOOP = "loop"
    PARALLEL = "parallel"
    JOIN = "join"


@dataclass(frozen=True)
class ConditionalEdge:
    """Conditional transition from a source node."""

    target: str
    condition: Callable[[AgentState], bool] | None = None
    kind: EdgeKind = EdgeKind.CONDITIONAL
    label: str | None = None

    def matches(self, state: AgentState) -> bool:
        if self.condition is None:
            return True
        return self.condition(state)
