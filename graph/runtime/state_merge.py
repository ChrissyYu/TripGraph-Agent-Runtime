"""State merge strategies for parallel graph branches."""

from __future__ import annotations

import copy
from enum import StrEnum
from typing import Any

from graph.runtime.agent_state import AgentState
from schemas.execution_graph import ExecutionGraphModel
from schemas.state_versioning import StateVersionStore


class MergeStrategy(StrEnum):
    LAST_WINS = "last_wins"
    DEEP_MERGE = "deep_merge"
    MERGE_LISTS = "merge_lists"
    FAIL_ON_CONFLICT = "fail_on_conflict"


class StateMergeConflictError(RuntimeError):
    pass


def merge_states(
    base: AgentState,
    branches: list[AgentState],
    *,
    strategy: MergeStrategy = MergeStrategy.DEEP_MERGE,
) -> AgentState:
    if not branches:
        return base
    if len(branches) == 1:
        return _merge_pair(base, branches[0], strategy=strategy)

    merged = base
    for branch in branches:
        merged = _merge_pair(merged, branch, strategy=strategy)
    return merged


def _merge_pair(
    left: AgentState,
    right: AgentState,
    *,
    strategy: MergeStrategy,
) -> AgentState:
    if strategy == MergeStrategy.LAST_WINS:
        return right

    if strategy == MergeStrategy.FAIL_ON_CONFLICT:
        conflicts = _detect_conflicts(left, right)
        if conflicts:
            raise StateMergeConflictError(f"Merge conflicts: {conflicts}")
        return _deep_merge(left, right)

    if strategy == MergeStrategy.MERGE_LISTS:
        return _merge_lists(left, right)

    return _deep_merge(left, right)


def _detect_conflicts(left: AgentState, right: AgentState) -> list[str]:
    conflicts: list[str] = []
    scalar_fields = (
        "plan",
        "current_step",
        "final_result",
        "execution_critique",
        "should_stop",
        "query",
    )
    for field in scalar_fields:
        lv = getattr(left, field)
        rv = getattr(right, field)
        if lv is not None and rv is not None and lv != rv:
            conflicts.append(field)
    return conflicts


def _merge_execution_graphs(
    left: ExecutionGraphModel | None,
    right: ExecutionGraphModel | None,
) -> ExecutionGraphModel | None:
    if not left:
        return right
    if not right:
        return left

    merged = left.model_copy(deep=True)
    seen_nodes = {(r.node_id, r.sequence) for r in merged.node_records}
    for record in right.node_records:
        key = (record.node_id, record.sequence)
        if key not in seen_nodes:
            merged.node_records.append(record)
            seen_nodes.add(key)

    seen_edges = {(e.source, e.target, e.sequence) for e in merged.edge_records}
    for edge in right.edge_records:
        key = (edge.source, edge.target, edge.sequence)
        if key not in seen_edges:
            merged.edge_records.append(edge)

    merged.node_records.sort(key=lambda r: r.sequence)
    merged.edge_records.sort(key=lambda e: e.sequence)
    return merged


def _merge_version_stores(
    left: StateVersionStore | None,
    right: StateVersionStore | None,
) -> StateVersionStore | None:
    if not left:
        return right
    if not right:
        return left

    merged = left.model_copy(deep=True)
    seen = {v.version_id for v in merged.versions}
    for version in right.versions:
        if version.version_id not in seen:
            merged.versions.append(version)
            seen.add(version.version_id)

    if right.current_version_id:
        merged.current_version_id = right.current_version_id
    merged.branches.update(right.branches)
    if right.branch_id:
        merged.branch_id = right.branch_id
    return merged


def _deep_merge(left: AgentState, right: AgentState) -> AgentState:
    data = left.model_dump()
    right_data = right.model_dump()

    data["observations"] = {**data.get("observations", {}), **right_data.get("observations", {})}
    data["memory"] = {**data.get("memory", {}), **right_data.get("memory", {})}

    for key in ("messages", "execution_trace", "graph_trace", "replan_history"):
        data[key] = _dedupe_list(data.get(key, []) + right_data.get(key, []))

    for key in ("short_term_memory", "long_term_memory", "episodic_memory"):
        data[key] = _dedupe_list(data.get(key, []) + right_data.get(key, []))

    for field in ("plan", "current_step", "final_result", "execution_critique", "plan_state"):
        if right_data.get(field) is not None:
            data[field] = right_data[field]

    data["should_stop"] = left.should_stop or right.should_stop
    data["replan_attempts"] = max(left.replan_attempts, right.replan_attempts)
    data["execution_graph"] = _merge_execution_graphs(left.execution_graph, right.execution_graph)
    data["version_store"] = _merge_version_stores(left.version_store, right.version_store)
    data["state_version_id"] = right.state_version_id or left.state_version_id

    return AgentState.model_validate(data)


def _merge_lists(left: AgentState, right: AgentState) -> AgentState:
    merged = _deep_merge(left, right)
    for key in ("messages", "execution_trace", "graph_trace"):
        merged_list = getattr(left, key) + getattr(right, key)
        object.__setattr__(merged, key, _dedupe_list(merged_list))
    return merged


def _dedupe_list(items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for item in items:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(copy.deepcopy(item))
    return result
