"""Graph runtime runner with streaming support."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

from core.logging import get_logger
from graph.runtime.agent_state import AgentState
from graph.runtime.core.graph import Graph
from graph.runtime.deps import RuntimeDependencies
from graph.runtime.execution_policy import ExecutionPolicy
from graph.runtime.replay_debug import GraphReplayDebugger
from graph.runtime.state_versioning import StateVersionManager
from graph.runtime.workflow import AgentWorkflowBuilder
from persistence.db.models import ExecutionStatus
from schemas.graph_runtime import GraphExecuteResponse, NodeTimelineEntry
from schemas.streaming import StreamEvent, StreamEventType

if TYPE_CHECKING:
    from observability.observer import MetricsContext, MetricsObserver
    from persistence.recorder import ExecutionContext, ExecutionRecorder

logger = get_logger(__name__)


class GraphRuntimeRunner:
    """Phase 4 primary runtime; Phase 3 orchestrator remains as fallback."""

    def __init__(
        self,
        deps: RuntimeDependencies,
        *,
        max_iterations: int = 50,
        recorder: ExecutionRecorder | None = None,
        metrics_observer: MetricsObserver | None = None,
    ) -> None:
        self._deps = deps
        self._workflow = AgentWorkflowBuilder(deps, max_iterations=max_iterations)
        self._recorder = recorder
        self._metrics = metrics_observer

    @property
    def workflow(self) -> Graph:
        return self._workflow.build()

    @property
    def debugger(self) -> GraphReplayDebugger:
        return GraphReplayDebugger(self)

    async def invoke(
        self,
        query: str,
        *,
        session_id: str = "default",
        policy: ExecutionPolicy | None = None,
        merge_strategy: str | None = None,
        initial_state: AgentState | None = None,
    ) -> GraphExecuteResponse:
        from core.llm.fallback_trace import clear_fallback_events

        clear_fallback_events()
        state = initial_state or self._initial_state(query, session_id=session_id)
        if initial_state is None:
            state.append_message("user", query)
        elif query and state.query != query:
            state.query = query
        if merge_strategy:
            state.memory["merge_strategy"] = merge_strategy
        graph = self._workflow.build()
        active_policy = policy or ExecutionPolicy()
        exec_ctx, metrics_ctx = self._begin_execution(
            session_id=session_id,
            query=query,
            graph_id=graph.graph_id,
        )

        try:
            final_state = await self._run_graph(
                graph,
                state,
                policy=active_policy,
                exec_ctx=exec_ctx,
                metrics_ctx=metrics_ctx,
            )
            self._finish_execution(
                exec_ctx,
                metrics_ctx,
                state=final_state,
                status=ExecutionStatus.COMPLETED,
            )
            response = self._to_response(final_state)
            execution_id = self._execution_id(exec_ctx, metrics_ctx)
            if execution_id is not None:
                response.execution_id = execution_id
            return response
        except Exception as exc:
            self._finish_execution(
                exec_ctx,
                metrics_ctx,
                state=state,
                status=ExecutionStatus.FAILED,
                error_message=str(exc),
            )
            raise

    async def stream(
        self,
        query: str,
        *,
        session_id: str = "default",
        policy: ExecutionPolicy | None = None,
        merge_strategy: str | None = None,
        initial_state: AgentState | None = None,
    ) -> AsyncIterator[StreamEvent]:
        state = initial_state or self._initial_state(query, session_id=session_id)
        if initial_state is None:
            state.append_message("user", query)
        elif query and state.query != query:
            state.query = query
        if merge_strategy:
            state.memory["merge_strategy"] = merge_strategy
        graph = self._workflow.build()
        active_policy = policy or ExecutionPolicy()
        exec_ctx, metrics_ctx = self._begin_execution(
            session_id=session_id,
            query=query,
            graph_id=graph.graph_id,
        )
        execution_id = self._execution_id(exec_ctx, metrics_ctx)

        yield StreamEvent(
            event=StreamEventType.START,
            session_id=session_id,
            data={
                "runtime": "graph",
                "graph_id": graph.graph_id,
                "mode": active_policy.mode.value,
                "seed": active_policy.seed,
                "execution_id": execution_id,
            },
        )

        try:
            async for event in graph.astream(state, policy=active_policy):
                self._on_graph_event(exec_ctx, metrics_ctx, event)

                event_type = event.get("type")
                if event_type == "node_start":
                    yield StreamEvent(
                        event=StreamEventType.GRAPH_NODE,
                        session_id=session_id,
                        data={
                            "phase": "start",
                            "node_id": event["node_id"],
                            "input_state_hash": event.get("input_state_hash"),
                            "sequence": event.get("sequence"),
                        },
                    )
                elif event_type == "node_end":
                    yield StreamEvent(
                        event=StreamEventType.GRAPH_NODE,
                        session_id=session_id,
                        data={
                            "phase": "end",
                            "node_id": event["node_id"],
                            "input_state_hash": event.get("input_state_hash"),
                            "output_state_hash": event.get("output_state_hash"),
                            "state_delta": event.get("state_delta"),
                            "sequence": event.get("sequence"),
                            "replayed": event.get("replayed", False),
                        },
                    )
                elif event_type == "parallel_fanout":
                    yield StreamEvent(
                        event=StreamEventType.GRAPH_STEP,
                        session_id=session_id,
                        data={
                            "phase": "parallel_fanout",
                            "source": event["source"],
                            "branches": event["branches"],
                            "join_node": event["join_node"],
                        },
                    )
                elif event_type == "parallel_done":
                    yield StreamEvent(
                        event=StreamEventType.GRAPH_STEP,
                        session_id=session_id,
                        data={"phase": "parallel_done", "sequence": event.get("sequence")},
                    )
                elif event_type == "edge":
                    yield StreamEvent(
                        event=StreamEventType.GRAPH_STEP,
                        session_id=session_id,
                        data={
                            "source": event["source"],
                            "target": event["target"],
                            "label": event.get("label"),
                        },
                    )
                elif event_type == "state":
                    state = event["state"]
                    yield StreamEvent(
                        event=StreamEventType.TOKEN,
                        session_id=session_id,
                        data={"content": state.final_result or ""},
                    )
        except Exception as exc:
            logger.exception("Graph runtime stream failed")
            self._finish_execution(
                exec_ctx,
                metrics_ctx,
                state=state,
                status=ExecutionStatus.FAILED,
                error_message=str(exc),
            )
            yield StreamEvent(
                event=StreamEventType.ERROR,
                session_id=session_id,
                data={"message": str(exc)},
            )
            return

        self._finish_execution(
            exec_ctx,
            metrics_ctx,
            state=state,
            status=ExecutionStatus.COMPLETED,
        )

        response = self._to_response(state)
        if execution_id is not None:
            response.execution_id = execution_id
        yield StreamEvent(
            event=StreamEventType.DONE,
            session_id=session_id,
            data=response.model_dump(),
        )

    async def _run_graph(
        self,
        graph: Graph,
        state: AgentState,
        *,
        policy: ExecutionPolicy,
        exec_ctx: ExecutionContext | None = None,
        metrics_ctx: MetricsContext | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> AgentState:
        async for event in graph.astream(state, policy=policy):
            self._on_graph_event(exec_ctx, metrics_ctx, event)
            if on_event is not None:
                on_event(event)
            if event.get("type") == "state":
                state = event["state"]
        return state

    def _begin_execution(
        self,
        *,
        session_id: str,
        query: str,
        graph_id: str | None,
    ) -> tuple[ExecutionContext | None, MetricsContext | None]:
        exec_ctx: ExecutionContext | None = None
        metrics_ctx: MetricsContext | None = None

        if self._recorder is not None:
            exec_ctx = self._recorder.begin(
                session_id=session_id,
                query=query,
                graph_id=graph_id,
            )

        if self._metrics is not None:
            metrics_ctx = self._metrics.begin(
                session_id=session_id,
                query=query,
                graph_id=graph_id,
                execution_id=exec_ctx.execution_id if exec_ctx else None,
            )

        return exec_ctx, metrics_ctx

    def _finish_execution(
        self,
        exec_ctx: ExecutionContext | None,
        metrics_ctx: MetricsContext | None,
        *,
        state: AgentState,
        status: ExecutionStatus,
        error_message: str | None = None,
    ) -> None:
        if self._recorder is not None and exec_ctx is not None:
            self._recorder.finish(
                exec_ctx,
                state,
                status=status,
                error_message=error_message,
            )
        if self._metrics is not None and metrics_ctx is not None:
            self._metrics.finish(
                metrics_ctx,
                status=status.value,
                error_message=error_message,
            )

    def _on_graph_event(
        self,
        exec_ctx: ExecutionContext | None,
        metrics_ctx: MetricsContext | None,
        event: dict[str, Any],
    ) -> None:
        if self._recorder is not None and exec_ctx is not None:
            self._recorder.on_graph_event(exec_ctx, event)
        if self._metrics is not None and metrics_ctx is not None:
            self._metrics.on_graph_event(metrics_ctx, event)

    @staticmethod
    def _execution_id(
        exec_ctx: ExecutionContext | None,
        metrics_ctx: MetricsContext | None,
    ) -> str | None:
        if exec_ctx is not None:
            return exec_ctx.execution_id
        if metrics_ctx is not None:
            return metrics_ctx.execution_id
        return None

    @staticmethod
    def _initial_state(query: str, *, session_id: str) -> AgentState:
        state = AgentState(session_id=session_id, query=query)
        state.append_message("user", query)
        return state

    def _to_response(self, state: AgentState) -> GraphExecuteResponse:
        execution_graph = state.execution_graph
        return GraphExecuteResponse(
            session_id=state.session_id,
            plan=state.plan,
            graph_trace=list(state.graph_trace),
            execution_trace=list(state.execution_trace),
            node_timeline=self._build_timeline(state),
            final_result=state.final_result or "",
            execution_critique=state.execution_critique,
            replan_history=list(state.replan_history),
            state_summary=state.summary(),
            runtime="graph",
            execution_graph=execution_graph.to_dag_json() if execution_graph else None,
            execution_graph_mermaid=execution_graph.to_mermaid() if execution_graph else None,
            execution_graph_dot=execution_graph.to_graphviz() if execution_graph else None,
            execution_seed=state.execution_seed or (
            state.execution_graph.seed if state.execution_graph else None
        ),
            state_version_id=state.state_version_id,
            version_summary=(
                {
                    "current_version_id": state.version_store.current_version_id,
                    "branch_id": state.version_store.branch_id,
                    "version_count": len(state.version_store.versions),
                    "branches": list(state.version_store.branches.keys()),
                }
                if state.version_store
                else None
            ),
        )

    @staticmethod
    def rollback_state(state: AgentState, version_id: str) -> AgentState:
        return StateVersionManager.rollback(state, version_id)

    @staticmethod
    def fork_branch(
        state: AgentState,
        *,
        from_version_id: str | None = None,
        branch_name: str | None = None,
    ) -> tuple[AgentState, str]:
        branch_id = StateVersionManager.fork_branch(
            state,
            from_version_id=from_version_id,
            branch_name=branch_name,
        )
        return state, branch_id

    @staticmethod
    def diff_versions(state: AgentState, version_a: str, version_b: str) -> dict:
        return StateVersionManager.diff(state, version_a, version_b)

    async def replay_from_branch(
        self,
        state_snapshot: dict,
        *,
        from_version_id: str,
        query: str,
        session_id: str = "default",
        branch_name: str | None = None,
        policy: ExecutionPolicy | None = None,
    ) -> GraphExecuteResponse:
        state = AgentState.from_api_snapshot(state_snapshot)
        StateVersionManager.fork_branch(
            state,
            from_version_id=from_version_id,
            branch_name=branch_name,
        )
        state.query = query
        state.session_id = session_id
        state.messages = [{"role": "user", "content": query}]
        graph = self._workflow.build()
        final_state = await graph.invoke(state, policy=policy or ExecutionPolicy())
        return self._to_response(final_state)

    @staticmethod
    def _build_timeline(state: AgentState) -> list[NodeTimelineEntry]:
        timeline: list[NodeTimelineEntry] = []
        starts: dict[str, int] = {}

        for entry in state.graph_trace:
            if entry.event == "node_start":
                starts[entry.node_id] = entry.step_index
            elif entry.event == "node_end" and entry.node_id in starts:
                started = starts[entry.node_id]
                timeline.append(
                    NodeTimelineEntry(
                        node_id=entry.node_id,
                        started_at_step=started,
                        ended_at_step=entry.step_index,
                        duration_steps=entry.step_index - started,
                        status="completed",
                        detail=entry.data,
                    ),
                )
        return timeline
