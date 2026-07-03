"""Plan execution API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_plan_service
from app.services.plan_service import PlanService
from core.exceptions import PlanValidationError
from schemas.api_response import ApiResponse, ok
from schemas.plan import PlanExecuteRequest, PlanExecuteResponse, PlanValidationReport

router = APIRouter()


@router.post("/execute", response_model=PlanExecuteResponse)
async def plan_execute(
    body: PlanExecuteRequest,
    service: PlanService = Depends(get_plan_service),
) -> PlanExecuteResponse:
    try:
        return await service.execute(body)
    except PlanValidationError as exc:
        report = PlanValidationReport(success=False, errors=exc.errors or [str(exc)])
        raise HTTPException(
            status_code=422,
            detail={
                "message": report.readable_message(),
                "validation": report.model_dump(),
            },
        ) from exc


@router.post("/execute/envelope", response_model=ApiResponse[PlanExecuteResponse])
async def plan_execute_envelope(
    body: PlanExecuteRequest,
    service: PlanService = Depends(get_plan_service),
) -> ApiResponse[PlanExecuteResponse]:
    try:
        return ok(await service.execute(body))
    except PlanValidationError as exc:
        report = PlanValidationReport(success=False, errors=exc.errors or [str(exc)])
        raise HTTPException(
            status_code=422,
            detail={
                "message": report.readable_message(),
                "validation": report.model_dump(),
            },
        ) from exc
