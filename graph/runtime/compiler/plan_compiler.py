"""Compile Plan into parallel step-level execution graph."""

from __future__ import annotations

from graph.runtime.agent_state import AgentState
from graph.runtime.core.edge import EdgeKind
from graph.runtime.core.graph import END, Graph
from graph.runtime.deps import RuntimeDependencies
from graph.runtime.nodes import router_node
from graph.runtime.state_merge import MergeStrategy
from schemas.plan import Plan, PlanStep, StepStatus


class PlanGraphCompiler:
    """Compile plan steps into a DAG with parallel fan-out/fan-in per level."""

    def __init__(
        self,
        deps: RuntimeDependencies,
        *,
        merge_strategy: MergeStrategy = MergeStrategy.DEEP_MERGE,
    ) -> None:
        self._deps = deps
        self._merge_strategy = merge_strategy

    def compile(self, plan: Plan) -> Graph:
        levels = self._topological_levels(plan)
        graph = Graph(
            graph_id=f"plan:{plan.goal[:32]}",
            entry="plan_entry",
            termination=lambda state: (
                state.plan_state is not None and state.plan_state.all_steps_finished()
            ),
            max_iterations=max(len(plan.steps) * 4, 10),
            merge_strategy=self._merge_strategy,
        )

        graph.add_node("plan_entry", self._entry_node)
        routing_hints = {
            str(step.id): {
                "task": step.task,
                "tool_hint": step.tool_hint,
                "dependency": step.dependency or [],
            }
            for step in plan.steps
        }
        graph.metadata["routing_hints"] = routing_hints
        graph.metadata["plan_goal"] = plan.goal
        graph.metadata["parallel_levels"] = [[s.id for s in level] for level in levels]

        for step in plan.steps:
            graph.add_node(self._step_node_id(step.id), self._make_step_node(step))

        sink_id = "plan_sink"
        graph.add_node(sink_id, self._sink_node)

        previous = "plan_entry"
        for level_index, level in enumerate(levels):
            join_id = f"plan_join_{level_index}"
            branch_ids = [self._step_node_id(step.id) for step in level]
            if level_index + 1 < len(levels):
                next_level = levels[level_index + 1]
                next_after_join = self._step_node_id(next_level[0].id)
            else:
                next_after_join = sink_id

            if len(branch_ids) == 1:
                graph.add_edge(previous, branch_ids[0], kind=EdgeKind.DIRECT)
                graph.add_edge(branch_ids[0], join_id, kind=EdgeKind.DIRECT)
            else:
                graph.add_parallel_fanout(previous, branch_ids, join_node=join_id)

            graph.add_join_node(
                join_id,
                wait_for=branch_ids,
                next_node=next_after_join,
            )
            previous = join_id

        graph.add_edge(sink_id, END)
        return graph

    @staticmethod
    def _topological_levels(plan: Plan) -> list[list[PlanStep]]:
        remaining = {step.id: step for step in plan.steps}
        finished: set[int] = set()
        levels: list[list[PlanStep]] = []

        while remaining:
            ready = [
                step
                for step in remaining.values()
                if all(dep in finished for dep in (step.dependency or []))
            ]
            if not ready:
                break
            levels.append(sorted(ready, key=lambda s: s.id))
            for step in ready:
                finished.add(step.id)
                remaining.pop(step.id)

        return levels

    @staticmethod
    async def _entry_node(state: AgentState) -> AgentState:
        state.observations["plan_graph_entered"] = True
        return state

    def _make_step_node(self, step: PlanStep):
        async def _run(state: AgentState) -> AgentState:
            if state.plan_state is None:
                return state
            status = state.plan_state.get_step_status(step.id)
            if status in (StepStatus.COMPLETED, StepStatus.SKIPPED, StepStatus.FAILED):
                return state
            if not state.plan_state.dependencies_met(step.id):
                return state

            await router_node(state, self._deps)
            state.current_step = step.id
            step_obj = state.plan_state._find_step(step.id)
            await self._deps.plan_executor._run_step_with_recovery(step_obj, state.plan_state)

            state.plan = state.plan_state.plan
            state.execution_trace = list(state.plan_state.execution_trace)
            result = state.plan_state.step_results.get(step.id)
            state.observations.setdefault("step_outputs", {})[step.id] = (
                result.observation if result else None
            )
            return state

        return _run

    @staticmethod
    async def _sink_node(state: AgentState) -> AgentState:
        state.observations["plan_graph_complete"] = True
        return state

    @staticmethod
    def _step_node_id(step_id: int) -> str:
        return f"step_{step_id}"
