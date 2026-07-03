"""Execution persistence, replay, and profiling service."""

from __future__ import annotations

from typing import Any

from observability.profile import ExecutionProfileService
from persistence.replay_service import ExecutionReplayService
from schemas.persistence import ReplayExecutionRequest, SessionRestoreRequest


class ExecutionService:
    def __init__(
        self,
        *,
        replay_service: ExecutionReplayService | None,
        profile_service: ExecutionProfileService | None,
        persistence_enabled: bool,
        metrics_enabled: bool,
    ) -> None:
        self._replay_service = replay_service
        self._profile_service = profile_service
        self._persistence_enabled = persistence_enabled
        self._metrics_enabled = metrics_enabled

    @property
    def persistence_enabled(self) -> bool:
        return self._persistence_enabled and self._replay_service is not None

    @property
    def metrics_enabled(self) -> bool:
        return self._metrics_enabled and self._profile_service is not None

    async def get_execution(self, execution_id: str) -> dict[str, Any]:
        self._require_persistence()
        detail = await self._replay_service.get_execution(execution_id)  # type: ignore[union-attr]
        if detail is None:
            raise KeyError(f"Execution not found: {execution_id}")
        return detail

    def get_profile(self, execution_id: str) -> dict[str, Any]:
        self._require_metrics()
        profile = self._profile_service.get_profile(execution_id)  # type: ignore[union-attr]
        if profile is None:
            raise KeyError(f"Execution profile not found: {execution_id}")
        return profile

    async def replay(self, body: ReplayExecutionRequest) -> dict[str, Any]:
        self._require_persistence()
        return await self._replay_service.replay_execution(  # type: ignore[union-attr]
            body.execution_id,
            node_id=body.node_id,
            compare_with=body.compare_with,
        )

    async def restore_session(self, body: SessionRestoreRequest) -> dict[str, Any]:
        self._require_persistence()
        return await self._replay_service.restore_session(  # type: ignore[union-attr]
            body.session_id,
            query=body.query,
        )

    def _require_persistence(self) -> None:
        if not self.persistence_enabled:
            raise RuntimeError("Persistence is disabled")

    def _require_metrics(self) -> None:
        if not self.metrics_enabled:
            raise RuntimeError("Metrics are disabled")
