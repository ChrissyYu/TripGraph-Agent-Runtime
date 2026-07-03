"""Graph runtime API (Phase 4)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_graph_service
from app.services.graph_service import GraphService
from schemas.api_response import ApiMeta, ApiResponse, ok
from schemas.graph_runtime import (
    GraphExecuteRequest,
    GraphExecuteResponse,
    GraphReplayRequest,
    StateBranchReplayRequest,
    StateDiffRequest,
    StateForkRequest,
    StateRollbackRequest,
)
from streaming.sse import SSEResponse, stream_with_heartbeat

router = APIRouter()


@router.post("/execute", response_model=GraphExecuteResponse)
async def graph_execute(
    body: GraphExecuteRequest,
    service: GraphService = Depends(get_graph_service),
) -> GraphExecuteResponse | SSEResponse:
    if body.stream:
        return SSEResponse(stream_with_heartbeat(service.stream(body)))
    try:
        return await service.execute(body)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/execute/envelope", response_model=ApiResponse[GraphExecuteResponse])
async def graph_execute_envelope(
    body: GraphExecuteRequest,
    service: GraphService = Depends(get_graph_service),
) -> ApiResponse[GraphExecuteResponse]:
    if body.stream:
        raise HTTPException(status_code=400, detail="Use /graph/execute for streaming requests")
    try:
        result = await service.execute(body)
        return ok(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/replay")
async def graph_replay(
    body: GraphReplayRequest,
    service: GraphService = Depends(get_graph_service),
) -> dict:
    try:
        if body.node_id:
            return await service.replay_node(body.execution_graph, body.node_id)
        return await service.replay_all(body.execution_graph, session_id=body.session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/debug/inspect")
async def graph_debug_inspect(
    execution_graph_json: str,
    node_id: str,
    phase: str = "output",
    service: GraphService = Depends(get_graph_service),
) -> dict:
    try:
        payload = json.loads(execution_graph_json)
        return service.inspect_node(payload, node_id, phase=phase)
    except (json.JSONDecodeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid execution graph: {exc}") from exc


@router.post("/state/rollback")
async def graph_state_rollback(body: StateRollbackRequest) -> ApiResponse[dict]:
    payload = GraphService.rollback_state(body.state_snapshot, body.version_id)
    payload["session_id"] = body.session_id
    return ok(payload)


@router.post("/state/fork")
async def graph_state_fork(body: StateForkRequest) -> ApiResponse[dict]:
    payload = GraphService.fork_state(
        body.state_snapshot,
        from_version_id=body.from_version_id,
        branch_name=body.branch_name,
    )
    payload["session_id"] = body.session_id
    return ok(payload)


@router.post("/state/diff")
async def graph_state_diff(body: StateDiffRequest) -> ApiResponse[dict]:
    return ok(GraphService.diff_state(body.state_snapshot, body.version_a, body.version_b))


@router.post("/state/replay_branch", response_model=GraphExecuteResponse)
async def graph_state_replay_branch(
    body: StateBranchReplayRequest,
    service: GraphService = Depends(get_graph_service),
) -> GraphExecuteResponse:
    try:
        return await service.replay_branch(
            state_snapshot=body.state_snapshot,
            from_version_id=body.from_version_id,
            query=body.query,
            session_id=body.session_id,
            branch_name=body.branch_name,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
