"""State versioning: commit, rollback, diff, branch fork."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from graph.runtime.agent_state import AgentState
from graph.runtime.state_hash import hash_state, state_to_serializable
from schemas.state_versioning import StateVersion, StateVersionStore


def _snapshot_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    all_keys = set(before) | set(after)
    for key in sorted(all_keys):
        old = before.get(key)
        new = after.get(key)
        if old != new:
            delta[key] = {"before": old, "after": new}
    return delta


def _copy_state_fields(target: AgentState, source: AgentState) -> None:
    for key in AgentState.model_fields:
        object.__setattr__(target, key, getattr(source, key))


class StateVersionManager:
    """Manages versioned snapshots on AgentState."""

    @staticmethod
    def ensure_store(state: AgentState) -> StateVersionStore:
        if state.version_store is None:
            state.version_store = StateVersionStore()
        return state.version_store

    @classmethod
    def commit(cls, state: AgentState, *, node_id: str) -> StateVersion:
        store = cls.ensure_store(state)
        snapshot = copy.deepcopy(state_to_serializable(state))
        state_hash = hash_state(state)
        parent_id = store.current_version_id

        diff: dict[str, Any] = {}
        if parent_id:
            parent = store.get_version(parent_id)
            if parent:
                diff = _snapshot_diff(parent.snapshot, snapshot)

        version = StateVersion(
            version_id=str(uuid.uuid4()),
            parent_version_id=parent_id,
            branch_id=store.branch_id,
            node_id=node_id,
            state_hash=state_hash,
            snapshot=snapshot,
            diff_from_parent=diff,
        )
        store.versions.append(version)
        store.current_version_id = version.version_id
        state.state_version_id = version.version_id
        return version

    @classmethod
    def rollback(cls, state: AgentState, version_id: str) -> AgentState:
        store = cls.ensure_store(state)
        version = store.get_version(version_id)
        if version is None:
            raise KeyError(f"Unknown state version: {version_id}")

        restored = state.apply_snapshot(version.snapshot)
        restored.version_store = store
        restored.state_version_id = version.version_id
        store.current_version_id = version.version_id
        store.branch_id = version.branch_id
        return restored

    @classmethod
    def diff(
        cls,
        state: AgentState,
        version_a: str,
        version_b: str,
    ) -> dict[str, Any]:
        store = cls.ensure_store(state)
        a = store.get_version(version_a)
        b = store.get_version(version_b)
        if not a or not b:
            raise KeyError("Version not found for diff")
        return _snapshot_diff(a.snapshot, b.snapshot)

    @classmethod
    def fork_branch(
        cls,
        state: AgentState,
        *,
        from_version_id: str | None = None,
        branch_name: str | None = None,
    ) -> str:
        store = cls.ensure_store(state)
        base_id = from_version_id or store.current_version_id
        if not base_id:
            raise ValueError("No version to fork from")

        if store.get_version(base_id) is None:
            raise KeyError(f"Unknown state version: {base_id}")

        restored = cls.rollback(state, base_id)
        _copy_state_fields(state, restored)

        branch_id = branch_name or f"branch_{len(store.branches)}"
        store.branches[branch_id] = base_id
        store.branch_id = branch_id
        state.branch_id = branch_id
        return branch_id
