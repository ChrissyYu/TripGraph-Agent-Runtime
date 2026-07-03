"""Parallel fan-out / fan-in specifications."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParallelFanOut:
    """Fan-out from source to multiple parallel branches."""

    source: str
    branches: list[str]
    join_node: str


@dataclass
class JoinSpec:
    """Join node waiting for parallel branches."""

    join_id: str
    wait_for: list[str] = field(default_factory=list)
    next_node: str = "__end__"
