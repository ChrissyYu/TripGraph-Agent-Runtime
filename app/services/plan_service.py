"""Plan orchestration service facade."""

from __future__ import annotations

from plan.orchestrator import PlanOrchestrator
from schemas.plan import PlanExecuteRequest, PlanExecuteResponse


class PlanService:
    def __init__(self, orchestrator: PlanOrchestrator) -> None:
        self._orchestrator = orchestrator

    async def execute(self, body: PlanExecuteRequest) -> PlanExecuteResponse:
        return await self._orchestrator.run(body.query, session_id=body.session_id)
