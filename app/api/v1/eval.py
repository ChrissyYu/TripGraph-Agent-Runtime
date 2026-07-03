"""Evaluation & benchmark API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_eval_service, get_settings_dep
from app.services.eval_service import EvalService
from config.settings import Settings
from schemas.api_response import ApiMeta, ApiResponse, ok
from schemas.eval import EvalRunRequest

router = APIRouter()


@router.post("/run", response_model=ApiResponse[dict])
async def run_evaluation(
    body: EvalRunRequest,
    service: EvalService = Depends(get_eval_service),
    settings: Settings = Depends(get_settings_dep),
) -> ApiResponse[dict]:
    try:
        report = await service.run(body)
        return ok(
            report.model_dump(mode="json"),
            meta=ApiMeta(version=settings.app_version, environment=settings.environment),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/report", response_model=ApiResponse[dict])
async def get_evaluation_report(
    run_id: str | None = Query(default=None),
    service: EvalService = Depends(get_eval_service),
) -> ApiResponse[dict]:
    try:
        report = service.get_report(run_id)
        return ok(report.model_dump(mode="json"))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/regression", response_model=ApiResponse[dict])
async def get_regression_report(
    run_id: str | None = Query(default=None),
    service: EvalService = Depends(get_eval_service),
) -> ApiResponse[dict]:
    try:
        return ok(service.regression(run_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
