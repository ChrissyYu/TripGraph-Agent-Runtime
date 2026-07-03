"""Graph runtime nodes wrapping Phase 3 components."""

from __future__ import annotations

from graph.runtime.agent_state import AgentState
from graph.runtime.deps import RuntimeDependencies
from plan.final_synthesis import synthesize_final_result
from plan.repair import normalize_plan
from plan.state import PlanState
from schemas.plan import StepStatus


async def planner_node(state: AgentState, deps: RuntimeDependencies) -> AgentState:
    plan = await deps.planner.create_plan(state.query)
    normalize_result = normalize_plan(plan)
    plan = normalize_result.plan
    if normalize_result.notes:
        state.observations["plan_repair_notes"] = normalize_result.notes

    deps.validator.assert_valid(plan)

    plan_state = PlanState.from_plan(plan, session_id=state.session_id)
    plan_state.global_context.update(deps.resolver.enrich_context_from_query(state.query))

    state.plan = plan
    state.plan_state = plan_state
    state.observations["plan_steps"] = len(plan.steps)
    state.memory["user_query"] = state.query
    state.append_message("assistant", f"Plan created with {len(plan.steps)} steps")
    return state


async def router_node(state: AgentState, deps: RuntimeDependencies) -> AgentState:
    if not state.plan_state:
        return state

    routing: dict[str, dict] = {}
    policy_trace: list[dict] = list(state.observations.get("tool_policy_trace", []))
    policy_decisions: dict[str, dict] = dict(
        state.plan_state.global_context.get("tool_policy_decisions", {}),
    )

    for step in state.plan_state.plan.steps:
        if state.plan_state.get_step_status(step.id) in (
            StepStatus.COMPLETED,
            StepStatus.SKIPPED,
        ):
            continue
        task = step.task
        original_hint = step.tool_hint

        if not step.tool_hint:
            selection = await deps.tool_router.select(task)
            if selection.best_tool:
                step.tool_hint = selection.best_tool
            routing[str(step.id)] = {
                "task": task,
                "best_tool": selection.best_tool,
                "confidence": selection.confidence,
                "alternatives": [alt.model_dump() for alt in selection.alternatives],
                "source": "router",
            }
        else:
            routing[str(step.id)] = {
                "task": task,
                "tool_hint": step.tool_hint,
                "source": "plan",
            }

        if deps.tool_policy_engine is not None:
            decision = deps.tool_policy_engine.decide(
                tool_hint=original_hint or step.tool_hint,
                task=task,
                query=state.query,
            )
            if decision.selected_tool:
                step.tool_hint = decision.selected_tool
            routing[str(step.id)]["policy"] = decision.model_dump_json_safe()
            routing[str(step.id)]["selected_tool"] = decision.selected_tool
            policy_decisions[str(step.id)] = decision.model_dump_json_safe()
            if deps.tool_policy_tracer is not None:
                entry = deps.tool_policy_tracer.record(
                    decision,
                    session_id=state.session_id,
                    step_id=step.id,
                    task=task,
                    query=state.query,
                )
                policy_trace.append(entry.model_dump_json_safe())

    state.plan_state.global_context["tool_policy_decisions"] = policy_decisions
    if policy_trace:
        state.observations["tool_policy_trace"] = policy_trace
    state.observations["routing"] = routing
    state.memory["routing_hints"] = routing
    return state


async def execution_node(state: AgentState, deps: RuntimeDependencies) -> AgentState:
    if not state.plan_state or not state.plan:
        return state

    compiled = state.memory.get("compiled_plan_graph")
    if compiled is not None:
        from graph.runtime.hierarchical import AgentNode, StateMapper

        agent = AgentNode(
            "plan_executor",
            compiled,
            mapper=StateMapper.for_plan_execution(),
            description="Parallel plan execution agent",
        )
        return await agent(state)

    state.plan_state = await deps.plan_executor.execute(state.plan, state.plan_state)
    state.plan = state.plan_state.plan
    state.execution_trace = list(state.plan_state.execution_trace)
    state.current_step = state.plan_state.current_step
    state.observations["tool_outputs"] = state.plan_state.global_context.get("tool_outputs", {})
    if deps.tool_policy_tracer is not None and deps.tool_policy_tracer.entries:
        state.observations["tool_policy_trace"] = deps.tool_policy_tracer.to_observations_list()
        state.observations["tool_policy_counters"] = deps.tool_policy_tracer.counters
    return state


async def critic_node(state: AgentState, deps: RuntimeDependencies) -> AgentState:
    if not state.plan_state or not deps.critic.enabled:
        return state

    final_result = _synthesize_final(state)
    state.final_result = final_result
    state.execution_critique = await deps.critic.evaluate(state.plan_state, final_result)
    state.observations["critic"] = state.execution_critique.model_dump()
    state.memory["need_replan"] = state.execution_critique.need_replan
    return state


async def replanner_node(state: AgentState, deps: RuntimeDependencies) -> AgentState:
    if not state.plan_state or not state.execution_critique:
        return state

    outcome = await deps.replanner.handle(state.execution_critique, state.plan_state)
    state.replan_history.append(outcome.result)
    state.plan_state = outcome.updated_state
    state.plan = outcome.result.new_plan
    state.replan_attempts = deps.replanner.attempts_used
    state.execution_trace = list(state.plan_state.execution_trace)

    if outcome.result.replanned:
        from graph.runtime.compiler.plan_compiler import PlanGraphCompiler
        from graph.runtime.state_merge import MergeStrategy

        merge_raw = state.memory.get("merge_strategy", MergeStrategy.DEEP_MERGE)
        merge_strategy = (
            MergeStrategy(merge_raw) if isinstance(merge_raw, str) else merge_raw
        )
        compiler = PlanGraphCompiler(deps, merge_strategy=merge_strategy)
        state.memory["compiled_plan_graph"] = compiler.compile(state.plan)
        state.memory["need_replan"] = False
    return state


async def finalize_node(state: AgentState, deps: RuntimeDependencies) -> AgentState:
    state.final_result = _synthesize_final(state)
    state.should_stop = True
    state.append_message("assistant", state.final_result)
    return state


def _synthesize_final(state: AgentState) -> str:
    if not state.plan_state or not state.plan:
        return state.final_result or ""
    return synthesize_final_result(state.plan, state.plan_state)
