from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from agentqa.platform.api.deps import SESSION_COOKIE
from agentqa.platform.identity.models import IdentityError, Permission
from agentqa.platform.runs.read_models import RunReadModel
from agentqa.platform.security.taint import SecurityError
from agentqa.platform.storage.roles import ROLE_API

router = APIRouter(tags=["streams"])

FRAME_INTERVAL_SECONDS = 0.5
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "error", "inconclusive"}


async def _close(websocket: WebSocket, code: int, reason: str) -> None:
    await websocket.close(code=code, reason=reason)


@router.websocket("/api/v1/workspaces/{workspace_id}/runs/{run_id}/browser-stream")
async def browser_stream(websocket: WebSocket, workspace_id: UUID, run_id: UUID) -> None:
    runtime = getattr(websocket.app.state, "runtime", None)
    if runtime is None:
        await _close(websocket, 1011, "runtime_missing")
        return
    try:
        runtime.profile.origin_policy().check(
            websocket.headers.get("origin"), request_host=websocket.headers.get("host")
        )
    except SecurityError:
        await _close(websocket, 4403, "origin_rejected")
        return
    cookie = websocket.cookies.get(SESSION_COOKIE)
    if not cookie:
        await _close(websocket, 4401, "unauthenticated")
        return
    try:
        principal = await runtime.sessions.authenticate(cookie)
    except IdentityError:
        await _close(websocket, 4401, "unauthenticated")
        return
    try:
        await runtime.authorization.require(
            workspace_id=workspace_id, user_id=principal.user_id, permission=Permission.WORKSPACE_READ
        )
    except IdentityError:
        await _close(websocket, 4403, "permission_denied")
        return
    read_model = RunReadModel(runtime.engines[ROLE_API])
    state = await read_model.run_state(workspace_id=workspace_id, principal_id=principal.user_id, run_id=run_id)
    if state is None:
        await _close(websocket, 4404, "run_not_found")
        return
    await websocket.accept()
    sent_seq = 0
    try:
        while True:
            frame = None
            if runtime.browser_frames is not None:
                frame = await runtime.browser_frames.latest_frame(str(run_id))
            if frame is None:
                await websocket.send_json(
                    {
                        "type": "frame_unavailable",
                        "reason": "no_frame_source" if runtime.browser_frames is None else "no_frame",
                    }
                )
            elif int(frame.get("seq", 0)) > sent_seq:
                sent_seq = int(frame["seq"])
                await websocket.send_json(
                    {
                        "type": "frame",
                        "seq": sent_seq,
                        "viewport": frame.get("viewport") or {},
                        "dpr": frame.get("dpr", 1.0),
                        "media_type": frame.get("media_type", "image/png"),
                        "png_b64": frame.get("png_b64", ""),
                    }
                )
            state = await read_model.run_state(workspace_id=workspace_id, principal_id=principal.user_id, run_id=run_id)
            if state is not None and state["status"] in TERMINAL_STATUSES:
                await websocket.send_json({"type": "closed", "status": state["status"]})
                return
            await asyncio.sleep(FRAME_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        return
