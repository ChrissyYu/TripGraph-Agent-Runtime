"""State versioning schemas for graph runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class StateVersion(BaseModel):
    version_id: str
    parent_version_id: str | None = None
    branch_id: str = "main"
    node_id: str
    state_hash: str
    snapshot: dict[str, Any] = Field(default_factory=dict)
    diff_from_parent: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StateVersionStore(BaseModel):
    """Version history with branch support."""

    current_version_id: str | None = None
    branch_id: str = "main"
    versions: list[StateVersion] = Field(default_factory=list)
    branches: dict[str, str] = Field(default_factory=lambda: {"main": "main"})

    def get_version(self, version_id: str) -> StateVersion | None:
        for version in self.versions:
            if version.version_id == version_id:
                return version
        return None

    def lineage(self, version_id: str | None = None) -> list[StateVersion]:
        vid = version_id or self.current_version_id
        if not vid:
            return []
        chain: list[StateVersion] = []
        cursor = vid
        while cursor:
            version = self.get_version(cursor)
            if not version:
                break
            chain.append(version)
            cursor = version.parent_version_id
        return list(reversed(chain))
