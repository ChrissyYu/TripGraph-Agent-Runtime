"""Hierarchical graph: subgraph as node, agent abstraction, state mapping."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from graph.runtime.agent_state import AgentState
from graph.runtime.core.graph import Graph
from graph.runtime.execution_policy import ExecutionPolicy


@dataclass
class StateMapper:
    """Maps state between parent and child graph scopes."""

    parent_to_child: Callable[[AgentState], AgentState]
    child_to_parent: Callable[[AgentState, AgentState], AgentState]

    @classmethod
    def identity(cls) -> StateMapper:
        return cls(
            parent_to_child=lambda s: s,
            child_to_parent=lambda parent, child: child,
        )

    @classmethod
    def scoped(cls, *, prefix: str) -> StateMapper:
        def to_child(parent: AgentState) -> AgentState:
            child = AgentState(
                session_id=parent.session_id,
                query=parent.query,
                branch_id=parent.branch_id,
            )
            child.memory = {f"{prefix}_{k}": v for k, v in parent.memory.items()}
            child.observations = dict(parent.observations)
            return child

        def to_parent(parent: AgentState, child: AgentState) -> AgentState:
            parent.observations[prefix] = child.observations
            parent.memory[f"{prefix}_result"] = child.final_result
            if child.final_result and not parent.final_result:
                parent.final_result = child.final_result
            parent.graph_trace.extend(child.graph_trace)
            if child.execution_graph:
                parent.memory[f"{prefix}_execution_graph"] = child.execution_graph.to_dag_json()
            return parent

        return cls(parent_to_child=to_child, child_to_parent=to_parent)

    @classmethod
    def for_plan_execution(cls) -> StateMapper:
        """Map parent workflow state into compiled plan subgraph and back."""

        def to_child(parent: AgentState) -> AgentState:
            child = AgentState(
                session_id=parent.session_id,
                query=parent.query,
                branch_id=parent.branch_id,
                plan=parent.plan,
                plan_state=parent.plan_state,
                execution_seed=parent.execution_seed,
            )
            child.memory = dict(parent.memory)
            child.observations = dict(parent.observations)
            if parent.execution_graph:
                child.execution_graph = parent.execution_graph
            if parent.version_store:
                child.version_store = parent.version_store
                child.state_version_id = parent.state_version_id
            return child

        def to_parent(parent: AgentState, child: AgentState) -> AgentState:
            parent.plan = child.plan
            parent.plan_state = child.plan_state
            parent.execution_trace = list(child.execution_trace)
            parent.current_step = child.current_step
            parent.observations.update(child.observations)
            parent.observations["tool_outputs"] = (
                child.plan_state.global_context.get("tool_outputs", {})
                if child.plan_state
                else parent.observations.get("tool_outputs", {})
            )
            if child.execution_graph:
                parent.execution_graph = child.execution_graph
            parent.graph_trace.extend(child.graph_trace)
            if child.version_store:
                parent.version_store = child.version_store
                parent.state_version_id = child.state_version_id
            return parent

        return cls(parent_to_child=to_child, child_to_parent=to_parent)


class SubgraphNode:
    """Execute a nested graph as a single node."""

    def __init__(
        self,
        node_id: str,
        subgraph: Graph,
        *,
        mapper: StateMapper | None = None,
    ) -> None:
        self.node_id = node_id
        self._subgraph = subgraph
        self._mapper = mapper or StateMapper.identity()

    async def __call__(self, parent_state: AgentState) -> AgentState:
        child_state = self._mapper.parent_to_child(parent_state)
        child_state.parent_graph_id = parent_state.session_id
        child_state.nested_graph_id = self._subgraph.graph_id

        policy = ExecutionPolicy(capture_state_snapshots=True)
        result_child = await self._subgraph.invoke(child_state, policy=policy)
        merged = self._mapper.child_to_parent(parent_state, result_child)
        merged.log_graph(self.node_id, "subgraph_complete", subgraph_id=self._subgraph.graph_id)
        merged.memory["subgraph_results"] = merged.memory.get("subgraph_results", {})
        merged.memory["subgraph_results"][self.node_id] = {
            "graph_id": self._subgraph.graph_id,
            "final_result": result_child.final_result,
        }
        return merged


class AgentNode(SubgraphNode):
    """Named agent encapsulating a child graph (agent-to-agent abstraction)."""

    def __init__(
        self,
        agent_id: str,
        subgraph: Graph,
        *,
        mapper: StateMapper | None = None,
        description: str = "",
    ) -> None:
        super().__init__(agent_id, subgraph, mapper=mapper)
        self.agent_id = agent_id
        self.description = description

    async def __call__(self, parent_state: AgentState) -> AgentState:
        parent_state.log_graph(self.agent_id, "agent_invoke", agent_id=self.agent_id)
        result = await super().__call__(parent_state)
        result.memory.setdefault("agent_calls", []).append(
            {
                "agent_id": self.agent_id,
                "description": self.description,
                "subgraph_id": self._subgraph.graph_id,
            },
        )
        return result
