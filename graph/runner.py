"""LangGraph workflow runner interface."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from graph.builder import CompiledGraph, GraphBuilder
from graph.state import GraphState
from schemas.streaming import StreamEvent, StreamEventType


class StubCompiledGraph:
    """Minimal stub used until LangGraph is wired in."""

    async def ainvoke(
        self,
        input: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {**input, "final_output": input.get("query", "")}

    async def astream(
        self,
        input: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {**input, "final_output": input.get("query", "")}


class DefaultGraphBuilder(GraphBuilder):
    """Placeholder builder; replace with real LangGraph StateGraph wiring."""

    def build(self) -> CompiledGraph:
        return self.build_stub()

    def build_stub(self) -> CompiledGraph:
        return StubCompiledGraph()


class GraphRunner:
    """High-level runner that executes compiled graphs."""

    def __init__(self, builder: GraphBuilder | None = None) -> None:
        self._graph: CompiledGraph = (builder or DefaultGraphBuilder()).build()

    async def run(self, state: GraphState) -> GraphState:
        result = await self._graph.ainvoke(dict(state))
        return GraphState(**result)

    async def stream(self, state: GraphState) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(
            event=StreamEventType.START,
            session_id=state.get("session_id"),
            data={"task_id": state.get("task_id")},
        )

        async for chunk in self._graph.astream(dict(state)):
            yield StreamEvent(
                event=StreamEventType.TOKEN,
                session_id=state.get("session_id"),
                data={"content": chunk.get("final_output", "")},
            )

        yield StreamEvent(
            event=StreamEventType.DONE,
            session_id=state.get("session_id"),
            data={"task_id": state.get("task_id")},
        )
