"""Agent workflow graph builder."""

from __future__ import annotations

from graph.runtime.agent_state import AgentState
from graph.runtime.compiler.plan_compiler import PlanGraphCompiler
from graph.runtime.core.edge import ConditionalEdge, EdgeKind
from graph.runtime.core.graph import END, Graph
from graph.runtime.deps import RuntimeDependencies
from graph.runtime.memory_nodes import memory_load_node, memory_persist_node
from graph.runtime.state_merge import MergeStrategy
from graph.runtime.nodes import (
    critic_node,
    execution_node,
    finalize_node,
    planner_node,
    replanner_node,
    router_node,
)


class AgentWorkflowBuilder:
    """Build macro agent graph: memory → planner → execute → critic → replan loop."""

    def __init__(self, deps: RuntimeDependencies, *, max_iterations: int = 50) -> None:
        self._deps = deps
        self._max_iterations = max_iterations

    def build(self) -> Graph:
        graph = Graph(
            graph_id="agent_workflow",
            entry="memory_load",
            termination=lambda state: state.should_stop,
            max_iterations=self._max_iterations,
        )

        graph.add_node("memory_load", lambda s: memory_load_node(s, self._deps))
        graph.add_node("planner", lambda s: planner_node(s, self._deps))
        graph.add_node("compile_plan", self._compile_plan_node)
        graph.add_node("router", lambda s: router_node(s, self._deps))
        graph.add_node("execution", lambda s: execution_node(s, self._deps))
        graph.add_node("memory_persist", lambda s: memory_persist_node(s, self._deps))
        graph.add_node("critic", lambda s: critic_node(s, self._deps))
        graph.add_node("replanner", lambda s: replanner_node(s, self._deps))
        graph.add_node("finalize", lambda s: finalize_node(s, self._deps))

        graph.add_edge("memory_load", "planner")
        graph.add_edge("planner", "compile_plan")
        graph.add_edge("compile_plan", "router")
        graph.add_edge("router", "execution")
        graph.add_edge("execution", "memory_persist")
        graph.add_edge("finalize", "memory_persist")
        graph.add_conditional_edges(
            "memory_persist",
            [
                ConditionalEdge(
                    target=END,
                    condition=lambda s: s.should_stop,
                    label="persist_and_finish",
                ),
                ConditionalEdge(target="critic", label="persist_and_continue"),
            ],
        )

        graph.add_conditional_edges(
            "critic",
            [
                ConditionalEdge(
                    target="replanner",
                    condition=lambda s: bool(
                        s.execution_critique
                        and s.execution_critique.need_replan
                        and s.replan_attempts < self._deps.replanner.config.max_replan_attempts,
                    ),
                    kind=EdgeKind.LOOP,
                    label="need_replan",
                ),
                ConditionalEdge(target="finalize", label="done"),
            ],
        )

        graph.add_loop_edge(
            "replanner",
            "router",
            condition=lambda s: not s.should_stop,
            label="re_execute",
        )
        return graph

    async def _compile_plan_node(self, state: AgentState) -> AgentState:
        if not state.plan:
            return state
        merge_raw = state.memory.get("merge_strategy", MergeStrategy.DEEP_MERGE)
        merge_strategy = (
            MergeStrategy(merge_raw) if isinstance(merge_raw, str) else merge_raw
        )
        compiler = PlanGraphCompiler(self._deps, merge_strategy=merge_strategy)
        compiled = compiler.compile(state.plan)
        state.memory["compiled_plan_graph"] = compiled
        state.memory["routing_hints"] = compiled.metadata.get("routing_hints", {})
        state.observations["compiled_graph_id"] = compiled.graph_id
        return state
