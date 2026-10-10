from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from agentqa.platform.api.deps import authenticate, get_runtime, to_api_error
from agentqa.platform.identity.models import IdentityError, Permission
from agentqa.platform.runs.read_models import RunReadModel
from agentqa.platform.storage.roles import ROLE_API

router = APIRouter(prefix="/api/v1", tags=["events"])

SSE_IDLE_LIMIT = 400
SSE_POLL_SECONDS = 0.05


async def _require(request: Request, workspace_id: UUID, permission: Permission):
    principal = await authenticate(request)
    runtime = get_runtime(request)
    try:
        await runtime.authorization.require(workspace_id=workspace_id, user_id=principal.user_id, permission=permission)
    except IdentityError as error:
        raise to_api_error(error) from error
    return principal


def _event_payload(event: dict) -> dict:
    return {
        "event_id": str(event["event_id"]),
        "run_seq": event["run_seq"],
        "execution_id": str(event["execution_id"]) if event.get("execution_id") else None,
        "execution_seq": event.get("execution_seq"),
        "type": event["type"],
    }


@router.get("/workspaces/{workspace_id}/runs/{run_id}/events")
async def list_events(
    request: Request,
    workspace_id: UUID,
    run_id: UUID,
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    events = await runtime.events.query_durable(
        workspace_id=workspace_id,
        principal_id=principal.user_id,
        run_id=run_id,
        after_run_seq=cursor,
        limit=limit,
    )
    payload = [_event_payload(event) for event in events]
    next_cursor = payload[-1]["run_seq"] if payload else cursor
    return {"events": payload, "cursor": next_cursor}


@router.get("/workspaces/{workspace_id}/runs/{run_id}/events/stream")
async def stream_events(
    request: Request,
    workspace_id: UUID,
    run_id: UUID,
    cursor: int = Query(default=0, ge=0),
) -> StreamingResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    read_model = RunReadModel(runtime.engines[ROLE_API])

    async def generate():
        sent = cursor
        snapshot = await read_model.run_state(workspace_id=workspace_id, principal_id=principal.user_id, run_id=run_id)
        yield _sse("snapshot", {"run_id": str(run_id), "cursor": sent, "state": _snapshot_state(snapshot)})
        idle = 0
        while True:
            if await request.is_disconnected():
                return
            events = await runtime.events.query_durable(
                workspace_id=workspace_id,
                principal_id=principal.user_id,
                run_id=run_id,
                after_run_seq=sent,
            )
            for event in events:
                sent = event["run_seq"]
                yield _sse("run_event", _event_payload(event), event_id=sent)
            if events:
                idle = 0
                continue
            state = await read_model.run_state(workspace_id=workspace_id, principal_id=principal.user_id, run_id=run_id)
            if state is not None and state["status"] in {"succeeded", "failed", "cancelled", "error", "inconclusive"}:
                yield _sse("closed", {"run_id": str(run_id), "cursor": sent, "status": state["status"]})
                return
            idle += 1
            if idle >= SSE_IDLE_LIMIT:
                yield _sse("timeout", {"run_id": str(run_id), "cursor": sent})
                return
            await asyncio.sleep(SSE_POLL_SECONDS)

    return StreamingResponse(generate(), media_type="text/event-stream")


def _snapshot_state(state: dict | None) -> dict | None:
    if state is None:
        return None
    return {
        "run_id": str(state["run_id"]),
        "status": state["status"],
        "verdict": state["verdict"],
        "gate": state.get("gate"),
        "reasons": list(state.get("reasons", [])),
        "snapshot_digest": state.get("snapshot_digest"),
        "last_run_seq": state["last_run_seq"],
        "executions": [
            {"execution_id": str(item["execution_id"]), "status": item["status"], "verdict": item["verdict"]}
            for item in state["executions"]
        ],
        "controls": [
            {
                "control_id": str(item["control_id"]),
                "action": item["action"],
                "requested_at": item["requested_at"].isoformat()
                if hasattr(item["requested_at"], "isoformat")
                else item["requested_at"],
                "effective_at": item["effective_at"].isoformat()
                if hasattr(item["effective_at"], "isoformat")
                else item["effective_at"],
                "effective_reason": item["effective_reason"],
            }
            for item in state.get("controls", [])
        ],
    }


def _sse(event: str, payload: dict, *, event_id: int | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(payload, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"
