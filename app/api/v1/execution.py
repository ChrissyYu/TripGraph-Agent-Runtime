"""Execution persistence, replay, and profiling API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_execution_service
from app.services.execution_service import ExecutionService
from schemas.api_response import ApiResponse, ok
from schemas.persistence import ReplayExecutionRequest, SessionRestoreRequest

router = APIRouter()


@router.get("/{execution_id}", response_model=ApiResponse[dict])
async def get_execution(
    execution_id: str,
    service: ExecutionService = Depends(get_execution_service),
) -> ApiResponse[dict]:
    try:
        return ok(await service.get_execution(execution_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{execution_id}/profile", response_model=ApiResponse[dict])
async def get_execution_profile(
    execution_id: str,
    service: ExecutionService = Depends(get_execution_service),
) -> ApiResponse[dict]:
    try:
        return ok(service.get_profile(execution_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/replay", response_model=ApiResponse[dict])
async def replay_execution(
    body: ReplayExecutionRequest,
    service: ExecutionService = Depends(get_execution_service),
) -> ApiResponse[dict]:
    try:
        return ok(await service.replay(body))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/session/restore", response_model=ApiResponse[dict])
async def restore_session(
    body: SessionRestoreRequest,
    service: ExecutionService = Depends(get_execution_service),
) -> ApiResponse[dict]:
    try:
        return ok(await service.restore_session(body))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
