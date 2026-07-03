"""Health and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.dependencies import get_health_service, get_settings_dep
from app.services.health_service import HealthService
from config.settings import Settings
from schemas.api_response import ApiMeta, ApiResponse, ok

router = APIRouter()


@router.get("/health")
async def health_check(
    service: HealthService = Depends(get_health_service),
) -> dict[str, str]:
    return service.health()


@router.get("/health/detailed")
async def detailed_health_check(
    service: HealthService = Depends(get_health_service),
) -> dict:
    return await service.detailed()


@router.get("/ready", response_model=ApiResponse[dict])
async def readiness_check(
    request: Request,
    service: HealthService = Depends(get_health_service),
    settings: Settings = Depends(get_settings_dep),
) -> ApiResponse[dict]:
    request_id = getattr(request.state, "request_id", None)
    return ok(
        service.readiness(),
        meta=ApiMeta(
            request_id=request_id,
            version=settings.app_version,
            environment=settings.environment,
        ),
    )
