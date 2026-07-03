"""Graph execution policy: deterministic, replay, debug."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Awaitable, Callable

from schemas.execution_graph import ExecutionGraphModel


class ExecutionMode(StrEnum):
    NORMAL = "normal"
    DETERMINISTIC = "deterministic"
    REPLAY = "replay"


PauseHook = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class ExecutionPolicy:
    """Controls graph execution semantics."""

    mode: ExecutionMode = ExecutionMode.NORMAL
    seed: int | None = None
    replay_graph: ExecutionGraphModel | None = None
    debug: bool = False
    pause_at_nodes: set[str] = field(default_factory=set)
    capture_state_snapshots: bool = False
    _pause_hook: PauseHook | None = field(default=None, repr=False)
    _replay_index: int = field(default=0, repr=False)

    def with_seed(self, seed: int) -> ExecutionPolicy:
        self.seed = seed
        if self.mode == ExecutionMode.NORMAL:
            self.mode = ExecutionMode.DETERMINISTIC
        return self

    def with_replay(self, graph: ExecutionGraphModel) -> ExecutionPolicy:
        self.mode = ExecutionMode.REPLAY
        self.replay_graph = graph
        self._replay_index = 0
        return self

    def with_debug(
        self,
        *,
        pause_at: set[str] | None = None,
        hook: PauseHook | None = None,
    ) -> ExecutionPolicy:
        self.debug = True
        self.capture_state_snapshots = True
        if pause_at:
            self.pause_at_nodes = pause_at
        self._pause_hook = hook
        return self

    def apply_random_seed(self) -> None:
        if self.seed is None:
            return
        import random

        random.seed(self.seed)

    def next_replay_record(self):
        if not self.replay_graph or self._replay_index >= len(self.replay_graph.node_records):
            return None
        record = self.replay_graph.node_records[self._replay_index]
        self._replay_index += 1
        return record

    def peek_replay_record(self, node_id: str):
        if not self.replay_graph:
            return None
        for record in self.replay_graph.node_records[self._replay_index :]:
            if record.node_id == node_id:
                return record
        return None

    async def maybe_pause(self, node_id: str, snapshot: dict[str, Any]) -> None:
        if not self.debug:
            return
        if self.pause_at_nodes and node_id not in self.pause_at_nodes:
            return
        if self._pause_hook is not None:
            await self._pause_hook(node_id, snapshot)
