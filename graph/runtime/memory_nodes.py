"""Memory integration nodes for graph runtime."""

from __future__ import annotations

import json

from graph.runtime.agent_state import AgentState
from graph.runtime.deps import RuntimeDependencies
from schemas.memory import MemoryEntry, MemoryQuery, MemoryScope


async def memory_load_node(state: AgentState, deps: RuntimeDependencies) -> AgentState:
    """Load short-term and long-term memory into graph state."""
    if deps.memory_store is None:
        return state

    store = deps.memory_store
    query = MemoryQuery(session_id=state.session_id, limit=50)

    short_entries = await store.get(MemoryQuery(session_id=state.session_id, scope=MemoryScope.SHORT_TERM, limit=50))
    long_entries = await store.get(MemoryQuery(session_id=state.session_id, scope=MemoryScope.LONG_TERM, limit=50))
    episodic_entries = await store.get(
        MemoryQuery(session_id=state.session_id, scope=MemoryScope.EPISODIC, limit=50),
    )

    state.short_term_memory = [entry.model_dump(mode="json") for entry in short_entries]
    state.long_term_memory = [entry.model_dump(mode="json") for entry in long_entries]
    state.episodic_memory = [entry.model_dump(mode="json") for entry in episodic_entries]
    state.memory["loaded_scopes"] = ["short_term", "long_term", "episodic"]
    state.memory["memory_query"] = query.model_dump()
    return state


async def memory_persist_node(state: AgentState, deps: RuntimeDependencies) -> AgentState:
    """Persist episodic execution history and key outputs to memory stores."""
    if deps.memory_store is None:
        return state

    store = deps.memory_store
    episode = {
        "query": state.query,
        "plan_goal": state.plan.goal if state.plan else None,
        "final_result": state.final_result,
        "execution_trace_count": len(state.execution_trace),
        "graph_nodes": state.execution_graph.node_ids() if state.execution_graph else [],
        "node_hashes": [
            {
                "node_id": record.node_id,
                "input": record.input_state_hash,
                "output": record.output_state_hash,
            }
            for record in (state.execution_graph.node_records if state.execution_graph else [])
        ],
    }

    await store.save(
        MemoryEntry(
            session_id=state.session_id,
            key=f"episode_{len(state.episodic_memory)}",
            content=json.dumps(episode, ensure_ascii=False),
            scope=MemoryScope.EPISODIC,
            metadata={"runtime": "graph"},
        ),
    )

    if state.query:
        await store.save(
            MemoryEntry(
                session_id=state.session_id,
                key="last_query",
                content=state.query,
                scope=MemoryScope.SHORT_TERM,
            ),
        )

    if state.final_result:
        await store.save(
            MemoryEntry(
                session_id=state.session_id,
                key="last_result",
                content=state.final_result,
                scope=MemoryScope.LONG_TERM,
                metadata={"plan_goal": state.plan.goal if state.plan else None},
            ),
        )

    state.episodic_memory.append(episode)
    state.memory["last_persisted_episode"] = episode
    return state
