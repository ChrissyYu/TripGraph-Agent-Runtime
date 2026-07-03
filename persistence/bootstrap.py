"""Bootstrap persistence layer when enabled."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from config.settings import Settings
from persistence.async_writer import AsyncWriteQueue
from persistence.db.sqlite_client import SQLiteClient
from persistence.recorder import ExecutionRecorder
from persistence.replay_service import ExecutionReplayService
from persistence.stores import (
    ExecutionStore,
    NodeStore,
    SessionStore,
    StateStore,
    ToolStore,
)
from tools.tracing import ToolTracer

if TYPE_CHECKING:
    from graph.runtime.runner import GraphRuntimeRunner
    from tools.executor import ToolExecutor


@dataclass
class PersistenceBundle:
    enabled: bool
    client: SQLiteClient | None = None
    writer: AsyncWriteQueue | None = None
    recorder: ExecutionRecorder | None = None
    replay_service: ExecutionReplayService | None = None


def build_persistence(settings: Settings) -> PersistenceBundle:
    if not settings.persistence_enabled:
        return PersistenceBundle(enabled=False)

    client = SQLiteClient(settings.persistence_db_path)
    writer = AsyncWriteQueue()
    stores = {
        "execution": ExecutionStore(client),
        "node": NodeStore(client),
        "tool": ToolStore(client),
        "state": StateStore(client),
        "session": SessionStore(client),
    }
    recorder = ExecutionRecorder(
        execution_store=stores["execution"],
        node_store=stores["node"],
        tool_store=stores["tool"],
        state_store=stores["state"],
        session_store=stores["session"],
        writer=writer,
        enabled=True,
    )
    replay_service = ExecutionReplayService(
        execution_store=stores["execution"],
        node_store=stores["node"],
        tool_store=stores["tool"],
        state_store=stores["state"],
        session_store=stores["session"],
    )
    return PersistenceBundle(
        enabled=True,
        client=client,
        writer=writer,
        recorder=recorder,
        replay_service=replay_service,
    )


def wire_tool_tracer(tool_executor: ToolExecutor, bundle: PersistenceBundle) -> None:
    if not bundle.enabled or bundle.recorder is None:
        return
    tool_executor._tracer = ToolTracer(on_record=bundle.recorder.on_tool_record)


def bind_runner(bundle: PersistenceBundle, runner: GraphRuntimeRunner) -> None:
    if bundle.replay_service is not None:
        bundle.replay_service.bind_runner(runner)
