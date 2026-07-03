"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.container import ApplicationContainer
from app.services.eval_service import EvalService
from app.services.execution_service import ExecutionService
from app.services.graph_service import GraphService
from app.services.health_service import HealthService
from app.services.plan_service import PlanService
from config.settings import Settings, get_settings


def get_container(request: Request) -> ApplicationContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="Application container not initialized")
    return container


def get_settings_dep() -> Settings:
    return get_settings()


def get_graph_service(request: Request) -> GraphService:
    return get_container(request).graph_service


def get_plan_service(request: Request) -> PlanService:
    return get_container(request).plan_service


def get_execution_service(request: Request) -> ExecutionService:
    return get_container(request).execution_service


def get_eval_service(request: Request) -> EvalService:
    return get_container(request).eval_service


def get_health_service(request: Request) -> HealthService:
    return get_container(request).health_service
