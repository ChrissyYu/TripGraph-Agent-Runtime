"""API route aggregation."""

from fastapi import APIRouter

from app.api.v1.chat import router as chat_router
from app.api.v1.eval import router as eval_router
from app.api.v1.execution import router as execution_router
from app.api.v1.graph import router as graph_router
from app.api.v1.health import router as health_router
from app.api.v1.legacy import router as legacy_router
from app.api.v1.plan import router as plan_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(graph_router, prefix="/graph", tags=["graph"])
api_router.include_router(plan_router, prefix="/plan", tags=["plan"])
api_router.include_router(execution_router, prefix="/execution", tags=["execution"])
api_router.include_router(eval_router, prefix="/eval", tags=["eval"])
api_router.include_router(chat_router, prefix="/chat", tags=["chat"])
api_router.include_router(legacy_router, tags=["legacy"])
