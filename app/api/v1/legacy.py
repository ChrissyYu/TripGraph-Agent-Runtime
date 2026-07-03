"""Backward-compatible legacy API routes (Phase 4–7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_eval_service, get_execution_service, get_graph_service, get_plan_service
from app.services.eval_service import EvalService
from app.services.execution_service import ExecutionService
from app.services.graph_service import GraphService
from app.services.plan_service import PlanService
from core.exceptions import PlanValidationError
from schemas.eval import EvalRunRequest
from schemas.graph_runtime import (
    GraphExecuteRequest,
    GraphExecuteResponse,
    GraphReplayRequest,
    StateBranchReplayRequest,
    StateDiffRequest,
    StateForkRequest,
    StateRollbackRequest,
)
from schemas.persistence import ReplayExecutionRequest, SessionRestoreRequest
from schemas.plan import PlanExecuteRequest, PlanExecuteResponse, PlanValidationReport
from streaming.sse import SSEResponse, stream_with_heartbeat

router = APIRouter(include_in_schema=False)


@router.post("/graph_execute", response_model=GraphExecuteResponse)
async def legacy_graph_execute(
    body: GraphExecuteRequest,
    service: GraphService = Depends(get_graph_service),
) -> GraphExecuteResponse | SSEResponse:
    if body.stream:
        return SSEResponse(stream_with_heartbeat(service.stream(body)))
    return await service.execute(body)


@router.post("/graph_replay")
async def legacy_graph_replay(
    body: GraphReplayRequest,
    service: GraphService = Depends(get_graph_service),
) -> dict:
    try:
        if body.node_id:
            return await service.replay_node(body.execution_graph, body.node_id)
        return await service.replay_all(body.execution_graph, session_id=body.session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/graph_debug/inspect")
async def legacy_graph_debug_inspect(
    execution_graph_json: str,
    node_id: str,
    phase: str = "output",
    service: GraphService = Depends(get_graph_service),
) -> dict:
    import json

    try:
        payload = json.loads(execution_graph_json)
        return service.inspect_node(payload, node_id, phase=phase)
    except (json.JSONDecodeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid execution graph: {exc}") from exc


@router.post("/graph_state/rollback")
async def legacy_graph_state_rollback(body: StateRollbackRequest) -> dict:
    payload = GraphService.rollback_state(body.state_snapshot, body.version_id)
    payload["session_id"] = body.session_id
    return payload


@router.post("/graph_state/fork")
async def legacy_graph_state_fork(body: StateForkRequest) -> dict:
    payload = GraphService.fork_state(
        body.state_snapshot,
        from_version_id=body.from_version_id,
        branch_name=body.branch_name,
    )
    payload["session_id"] = body.session_id
    return payload


@router.post("/graph_state/diff")
async def legacy_graph_state_diff(body: StateDiffRequest) -> dict:
    return GraphService.diff_state(body.state_snapshot, body.version_a, body.version_b)


@router.post("/graph_state/replay_branch", response_model=GraphExecuteResponse)
async def legacy_graph_state_replay_branch(
    body: StateBranchReplayRequest,
    service: GraphService = Depends(get_graph_service),
) -> GraphExecuteResponse:
    return await service.replay_branch(
        state_snapshot=body.state_snapshot,
        from_version_id=body.from_version_id,
        query=body.query,
        session_id=body.session_id,
        branch_name=body.branch_name,
    )


@router.post("/plan_execute", response_model=PlanExecuteResponse)
async def legacy_plan_execute(
    body: PlanExecuteRequest,
    service: PlanService = Depends(get_plan_service),
) -> PlanExecuteResponse:
    try:
        return await service.execute(body)
    except PlanValidationError as exc:
        report = PlanValidationReport(success=False, errors=exc.errors or [str(exc)])
        raise HTTPException(
            status_code=422,
            detail={"message": report.readable_message(), "validation": report.model_dump()},
        ) from exc


@router.get("/execution/{execution_id}")
async def legacy_get_execution(
    execution_id: str,
    service: ExecutionService = Depends(get_execution_service),
) -> dict:
    try:
        return await service.get_execution(execution_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/execution/{execution_id}/profile")
async def legacy_get_execution_profile(
    execution_id: str,
    service: ExecutionService = Depends(get_execution_service),
) -> dict:
    try:
        return service.get_profile(execution_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/replay_execution")
async def legacy_replay_execution(
    body: ReplayExecutionRequest,
    service: ExecutionService = Depends(get_execution_service),
) -> dict:
    try:
        return await service.replay(body)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/session/restore")
async def legacy_restore_session(
    body: SessionRestoreRequest,
    service: ExecutionService = Depends(get_execution_service),
) -> dict:
    try:
        return await service.restore_session(body)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/eval/run")
async def legacy_eval_run(
    body: EvalRunRequest,
    service: EvalService = Depends(get_eval_service),
) -> dict:
    try:
        report = await service.run(body)
        return report.model_dump(mode="json")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/eval/report")
async def legacy_eval_report(
    run_id: str | None = None,
    service: EvalService = Depends(get_eval_service),
) -> dict:
    try:
        return service.get_report(run_id).model_dump(mode="json")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/eval/regression")
async def legacy_eval_regression(
    run_id: str | None = None,
    service: EvalService = Depends(get_eval_service),
) -> dict:
    try:
        return service.regression(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
