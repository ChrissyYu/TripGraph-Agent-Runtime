"""State fingerprinting and delta computation for graph runtime."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from graph.runtime.agent_state import AgentState


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "summary"):
        return value.summary()
    return str(value)


def state_to_serializable(state: AgentState, *, include_plan_state: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messages": state.messages,
        "plan": state.plan.model_dump(mode="json") if state.plan else None,
        "current_step": state.current_step,
        "observations": state.observations,
        "execution_trace": [item.model_dump(mode="json") for item in state.execution_trace],
        "graph_trace": [item.model_dump(mode="json") for item in state.graph_trace],
        "short_term_memory": state.short_term_memory,
        "long_term_memory": state.long_term_memory,
        "episodic_memory": state.episodic_memory,
        "session_id": state.session_id,
        "query": state.query,
        "final_result": state.final_result,
        "execution_critique": (
            state.execution_critique.model_dump(mode="json") if state.execution_critique else None
        ),
        "replan_history": [item.model_dump(mode="json") for item in state.replan_history],
        "should_stop": state.should_stop,
        "replan_attempts": state.replan_attempts,
        "execution_seed": state.execution_seed,
        "state_version_id": state.state_version_id,
        "branch_id": state.branch_id,
    }
    memory = dict(state.memory)
    memory.pop("compiled_plan_graph", None)
    payload["memory"] = memory
    if include_plan_state:
        payload["plan_state"] = state.plan_state.summary() if state.plan_state else None
    return payload


def hash_state(state: AgentState, *, exclude_trace: bool = True) -> str:
    payload = state_to_serializable(state)
    if exclude_trace:
        payload["graph_trace"] = []
        payload["execution_trace"] = []
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=_json_default)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_state_delta(before: AgentState, after: AgentState) -> dict[str, Any]:
    before_payload = state_to_serializable(before)
    after_payload = state_to_serializable(after)
    delta: dict[str, Any] = {}

    all_keys = set(before_payload) | set(after_payload)
    for key in sorted(all_keys):
        old = before_payload.get(key)
        new = after_payload.get(key)
        if old != new:
            delta[key] = {"before": old, "after": new}
    return delta
