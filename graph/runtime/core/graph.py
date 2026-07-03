"""Graph execution engine with parallel, versioning, and policy support."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import AsyncIterator, Callable
from typing import Any

from core.logging import get_logger
from graph.runtime.agent_state import AgentState
from graph.runtime.core.edge import ConditionalEdge, EdgeKind
from graph.runtime.core.node import NodeFn
from graph.runtime.core.parallel import JoinSpec, ParallelFanOut
from graph.runtime.execution_policy import ExecutionMode, ExecutionPolicy
from graph.runtime.state_hash import compute_state_delta, hash_state, state_to_serializable
from graph.runtime.state_merge import MergeStrategy, merge_states
from graph.runtime.state_versioning import StateVersionManager
from schemas.execution_graph import ExecutionGraphModel, GraphEdgeRecord, NodeExecutionRecord

logger = get_logger(__name__)

END = "__end__"


class Graph:
    """Native graph engine with fan-out/fan-in and LangGraph-compatible surface."""

    def __init__(
        self,
        graph_id: str,
        *,
        entry: str,
        termination: Callable[[AgentState], bool] | None = None,
        max_iterations: int = 100,
        merge_strategy: MergeStrategy = MergeStrategy.DEEP_MERGE,
    ) -> None:
        self.graph_id = graph_id
        self.entry = entry
        self.termination = termination
        self.max_iterations = max_iterations
        self._merge_strategy = merge_strategy
        self._nodes: dict[str, NodeFn] = {}
        self._edges: dict[str, list[ConditionalEdge]] = {}
        self._fan_outs: list[ParallelFanOut] = []
        self._join_specs: dict[str, JoinSpec] = {}
        self._metadata: dict[str, Any] = {}

    @property
    def metadata(self) -> dict[str, Any]:
        return self._metadata

    def add_node(self, node_id: str, fn: NodeFn) -> Graph:
        self._nodes[node_id] = fn
        return self

    def add_subgraph_node(
        self,
        node_id: str,
        subgraph: Graph,
        *,
        mapper: Any = None,
    ) -> Graph:
        from graph.runtime.hierarchical import StateMapper, SubgraphNode

        return self.add_node(
            node_id,
            SubgraphNode(node_id, subgraph, mapper=mapper or StateMapper.identity()),
        )

    def add_agent_node(
        self,
        agent_id: str,
        subgraph: Graph,
        *,
        mapper: Any = None,
        description: str = "",
    ) -> Graph:
        from graph.runtime.hierarchical import AgentNode, StateMapper

        return self.add_node(
            agent_id,
            AgentNode(agent_id, subgraph, mapper=mapper, description=description),
        )

    def add_edge(self, source: str, target: str, *, kind: EdgeKind = EdgeKind.DIRECT) -> Graph:
        self._edges.setdefault(source, []).append(
            ConditionalEdge(target=target, kind=kind, label="default"),
        )
        return self

    def add_conditional_edges(
        self,
        source: str,
        edges: list[ConditionalEdge],
    ) -> Graph:
        self._edges.setdefault(source, []).extend(edges)
        return self

    def add_loop_edge(
        self,
        source: str,
        target: str,
        *,
        condition: Callable[[AgentState], bool],
        label: str = "loop",
    ) -> Graph:
        self._edges.setdefault(source, []).append(
            ConditionalEdge(target=target, condition=condition, kind=EdgeKind.LOOP, label=label),
        )
        return self

    def add_parallel_fanout(
        self,
        source: str,
        branches: list[str],
        *,
        join_node: str,
    ) -> Graph:
        self._fan_outs.append(ParallelFanOut(source=source, branches=branches, join_node=join_node))
        for branch in branches:
            self.add_edge(source, branch, kind=EdgeKind.PARALLEL)
            self.add_edge(branch, join_node, kind=EdgeKind.JOIN)
        return self

    def add_join_node(
        self,
        join_id: str,
        *,
        wait_for: list[str],
        next_node: str,
        fn: NodeFn | None = None,
    ) -> Graph:
        self._join_specs[join_id] = JoinSpec(
            join_id=join_id,
            wait_for=wait_for,
            next_node=next_node,
        )
        if fn is not None:
            self.add_node(join_id, fn)
        else:
            async def _join_pass(state: AgentState) -> AgentState:
                state.log_graph(join_id, "join_complete", waited_for=wait_for)
                return state

            self.add_node(join_id, _join_pass)
        if next_node and next_node != END:
            self.add_edge(join_id, next_node, kind=EdgeKind.DIRECT)
        return self

    def fan_out_for(self, source: str) -> ParallelFanOut | None:
        for fan_out in self._fan_outs:
            if fan_out.source == source:
                return fan_out
        return None

    async def invoke(
        self,
        state: AgentState,
        *,
        policy: ExecutionPolicy | None = None,
    ) -> AgentState:
        async for event in self.astream(state, policy=policy):
            if event.get("type") == "state":
                state = event["state"]
        return state

    async def astream(
        self,
        state: AgentState,
        *,
        policy: ExecutionPolicy | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        policy = policy or ExecutionPolicy()
        policy.apply_random_seed()
        state.execution_seed = policy.seed

        execution_graph = state.execution_graph or ExecutionGraphModel(
            graph_id=self.graph_id,
            session_id=state.session_id,
            seed=policy.seed,
            mode=policy.mode.value,
        )
        state.execution_graph = execution_graph

        current = self.entry
        iterations = 0
        sequence = 0
        edge_sequence = 0

        yield {"type": "graph_start", "graph_id": self.graph_id, "entry": self.entry, "policy": policy.mode.value}

        while current != END and iterations < self.max_iterations:
            if state.should_stop or (self.termination and self.termination(state)):
                state.log_graph(current, "early_stop", reason="termination")
                yield {"type": "early_stop", "node_id": current, "state": state}
                break

            fan_out = self.fan_out_for(current)
            if fan_out is not None:
                if current in self._nodes:
                    input_hash = hash_state(state)
                    yield {
                        "type": "node_start",
                        "node_id": current,
                        "state": state,
                        "input_state_hash": input_hash,
                        "sequence": sequence,
                    }
                    state, _ = await self._execute_node(
                        current,
                        state,
                        policy=policy,
                        execution_graph=execution_graph,
                        sequence=sequence,
                    )
                    sequence += 1
                    yield {
                        "type": "node_end",
                        "node_id": current,
                        "state": state,
                        "input_state_hash": input_hash,
                        "output_state_hash": hash_state(state),
                        "sequence": sequence - 1,
                    }

                async for event in self._run_parallel_fanout_stream(
                    fan_out,
                    state,
                    policy=policy,
                    execution_graph=execution_graph,
                    sequence_start=sequence,
                    edge_sequence_start=edge_sequence,
                ):
                    if event.get("type") == "state":
                        state = event["state"]
                    else:
                        yield event
                        if event.get("type") == "parallel_done":
                            state = event["state"]
                            sequence = event.get("sequence", sequence)
                            edge_sequence = event.get("edge_sequence", edge_sequence)

                join_spec = self._join_specs.get(fan_out.join_node)
                current = (
                    join_spec.next_node
                    if join_spec and join_spec.next_node
                    else self._resolve_next(fan_out.join_node, state) or END
                )
                iterations += 1
                continue

            if current not in self._nodes:
                raise KeyError(f"Unknown graph node: {current}")

            input_hash = hash_state(state)
            yield {
                "type": "node_start",
                "node_id": current,
                "state": state,
                "input_state_hash": input_hash,
                "sequence": sequence,
            }

            state, _ = await self._execute_node(
                current,
                state,
                policy=policy,
                execution_graph=execution_graph,
                sequence=sequence,
            )
            sequence += 1

            yield {
                "type": "node_end",
                "node_id": current,
                "state": state,
                "input_state_hash": input_hash,
                "output_state_hash": hash_state(state),
                "sequence": sequence - 1,
            }

            next_node = self._resolve_next(current, state)
            if next_node is None:
                break

            edge = self._matched_edge(current, state, next_node)
            execution_graph.add_edge_record(
                GraphEdgeRecord(
                    source=current,
                    target=next_node,
                    label=edge.label if edge else None,
                    kind=edge.kind.value if edge else None,
                    sequence=edge_sequence,
                ),
            )
            edge_sequence += 1
            yield {
                "type": "edge",
                "source": current,
                "target": next_node,
                "label": edge.label if edge else None,
                "kind": edge.kind.value if edge else None,
            }

            current = next_node
            iterations += 1

        yield {"type": "graph_end", "graph_id": self.graph_id, "iterations": iterations}
        yield {"type": "state", "state": state}

    async def _run_parallel_fanout_stream(
        self,
        fan_out: ParallelFanOut,
        state: AgentState,
        *,
        policy: ExecutionPolicy,
        execution_graph: ExecutionGraphModel,
        sequence_start: int,
        edge_sequence_start: int,
    ) -> AsyncIterator[dict[str, Any]]:
        state.log_graph(fan_out.source, "parallel_fanout", branches=fan_out.branches)
        yield {
            "type": "parallel_fanout",
            "source": fan_out.source,
            "branches": fan_out.branches,
            "join_node": fan_out.join_node,
        }

        branch_events: list[dict[str, Any]] = []
        edge_sequence = edge_sequence_start

        for branch_id in fan_out.branches:
            execution_graph.add_edge_record(
                GraphEdgeRecord(
                    source=fan_out.source,
                    target=branch_id,
                    label="parallel",
                    kind=EdgeKind.PARALLEL.value,
                    sequence=edge_sequence,
                ),
            )
            edge_sequence += 1

        async def run_branch(branch_id: str, seq: int) -> AgentState:
            branch_state = copy.deepcopy(state)
            input_hash = hash_state(branch_state)
            branch_events.append(
                {
                    "type": "node_start",
                    "node_id": branch_id,
                    "parallel": True,
                    "input_state_hash": input_hash,
                    "sequence": seq,
                },
            )
            updated, _ = await self._execute_node(
                branch_id,
                branch_state,
                policy=policy,
                execution_graph=execution_graph,
                sequence=seq,
            )
            branch_events.append(
                {
                    "type": "node_end",
                    "node_id": branch_id,
                    "parallel": True,
                    "input_state_hash": input_hash,
                    "output_state_hash": hash_state(updated),
                    "sequence": seq,
                },
            )
            return updated

        sequence = sequence_start
        branch_tasks = [
            run_branch(branch_id, sequence + index)
            for index, branch_id in enumerate(fan_out.branches)
        ]
        branch_states = list(await asyncio.gather(*branch_tasks))

        for branch_id in fan_out.branches:
            execution_graph.add_edge_record(
                GraphEdgeRecord(
                    source=branch_id,
                    target=fan_out.join_node,
                    label="join",
                    kind=EdgeKind.JOIN.value,
                    sequence=edge_sequence,
                ),
            )
            edge_sequence += 1

        for event in branch_events:
            yield event

        merged = merge_states(state, branch_states, strategy=self._merge_strategy)
        StateVersionManager.commit(merged, node_id=f"{fan_out.join_node}:merge")

        join_id = fan_out.join_node
        join_spec = self._join_specs.get(join_id)
        if join_spec and set(fan_out.branches) != set(join_spec.wait_for):
            logger.warning(
                "JoinSpec.wait_for %s does not match fan-out branches %s at %s",
                join_spec.wait_for,
                fan_out.branches,
                join_id,
            )
        if join_id in self._nodes:
            join_input_hash = hash_state(merged)
            yield {
                "type": "node_start",
                "node_id": join_id,
                "parallel": True,
                "input_state_hash": join_input_hash,
                "sequence": sequence + len(fan_out.branches),
            }
            merged, _ = await self._execute_node(
                join_id,
                merged,
                policy=policy,
                execution_graph=execution_graph,
                sequence=sequence + len(fan_out.branches),
            )
            yield {
                "type": "node_end",
                "node_id": join_id,
                "parallel": True,
                "input_state_hash": join_input_hash,
                "output_state_hash": hash_state(merged),
                "sequence": sequence + len(fan_out.branches),
            }

        sequence += len(fan_out.branches) + 1
        yield {
            "type": "parallel_done",
            "state": merged,
            "sequence": sequence,
            "edge_sequence": edge_sequence,
        }

    async def _execute_node(
        self,
        node_id: str,
        state: AgentState,
        *,
        policy: ExecutionPolicy,
        execution_graph: ExecutionGraphModel,
        sequence: int,
    ) -> tuple[AgentState, int]:
        if node_id not in self._nodes:
            raise KeyError(f"Unknown graph node: {node_id}")

        input_hash = hash_state(state)
        input_snapshot = state.snapshot() if policy.capture_state_snapshots else None
        replay_record = policy.peek_replay_record(node_id) if policy.mode == ExecutionMode.REPLAY else None

        state.log_graph(node_id, "node_start", input_state_hash=input_hash)
        await policy.maybe_pause(node_id, input_snapshot or {"input_state_hash": input_hash})

        before = copy.deepcopy(state)
        replayed = False

        if (
            policy.mode == ExecutionMode.REPLAY
            and replay_record is not None
            and replay_record.input_state_hash == input_hash
            and replay_record.output_state_snapshot is not None
        ):
            state = state.apply_snapshot(replay_record.output_state_snapshot)
            replayed = True
            policy.next_replay_record()
        else:
            state = await self._nodes[node_id](state)
            if policy.mode == ExecutionMode.REPLAY and replay_record is not None:
                if replay_record.input_state_hash != input_hash:
                    logger.warning(
                        "Replay input hash mismatch at %s: expected %s got %s",
                        node_id,
                        replay_record.input_state_hash,
                        input_hash,
                    )
                policy.next_replay_record()

        output_hash = hash_state(state)
        delta = compute_state_delta(before, state)
        output_snapshot = state.snapshot() if policy.capture_state_snapshots else None

        version = StateVersionManager.commit(state, node_id=node_id)

        node_record = NodeExecutionRecord(
            node_id=node_id,
            sequence=sequence,
            input_state_hash=input_hash,
            output_state_hash=output_hash,
            state_delta=_compact_delta(delta),
            input_state_snapshot=input_snapshot,
            output_state_snapshot=output_snapshot,
            replayed=replayed,
        )
        execution_graph.add_node_record(node_record)

        state.log_graph(
            node_id,
            "node_end",
            output_state_hash=output_hash,
            input_state_hash=input_hash,
            state_version_id=version.version_id,
            state_delta_keys=list(node_record.state_delta.keys()),
        )
        return state, 1

    def _resolve_next(self, source: str, state: AgentState) -> str | None:
        edges = self._edges.get(source, [])
        if not edges:
            return END

        for edge in edges:
            if edge.kind == EdgeKind.PARALLEL:
                continue
            if edge.matches(state):
                return edge.target
        return END

    def _matched_edge(
        self,
        source: str,
        state: AgentState,
        target: str,
    ) -> ConditionalEdge | None:
        for edge in self._edges.get(source, []):
            if edge.target == target and edge.matches(state):
                return edge
        return None


def _compact_delta(delta: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, change in delta.items():
        if key in ("graph_trace", "execution_graph", "version_store"):
            compact[key] = {"changed": True}
            continue
        compact[key] = change
    return compact
