from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
from typing import Any
from uuid import UUID

from agentqa.contracts.case import CaseContent
from agentqa.platform.runs.coordinator import ExecutionSpec, outcome_to_dict
from agentqa.platform.supervisor.commands import CommandRequest
from agentqa.platform.supervisor.runtime import SupervisorRuntime

MAX_LINE_BYTES = 262_144


class SupervisorServer:
    def __init__(
        self,
        runtime: SupervisorRuntime,
        token: str,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        coordinator: Any = None,
    ) -> None:
        self._runtime = runtime
        self._token = token
        self._host = host
        self._port = port
        self._coordinator = coordinator
        self._server: asyncio.AbstractServer | None = None
        self._monitor_stop: asyncio.Event | None = None
        self._monitor_task: asyncio.Task[None] | None = None

    @property
    def port(self) -> int:
        return self._port

    @property
    def runtime(self) -> SupervisorRuntime:
        return self._runtime

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._handle_client, self._host, self._port)
        self._port = self._server.sockets[0].getsockname()[1]
        self._monitor_stop = asyncio.Event()
        self._monitor_task = asyncio.create_task(self._runtime.monitor(self._monitor_stop))
        return self._port

    async def stop(self) -> None:
        if self._monitor_stop is not None:
            self._monitor_stop.set()
        if self._monitor_task is not None:
            await asyncio.gather(self._monitor_task, return_exceptions=True)
            self._monitor_task = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            token_line = await asyncio.wait_for(reader.readline(), timeout=10)
            hello = json.loads(token_line.decode("utf-8") or "{}")
            if not hmac.compare_digest(str(hello.get("token", "")), self._token):
                writer.write(_encode({"ok": False, "error": {"code": "unauthorized", "message": "token sai"}}))
                await writer.drain()
                return
            writer.write(_encode({"ok": True, "result": {"supervisor_id": self._runtime.config.supervisor_id}}))
            await writer.drain()
            while True:
                line = await reader.readline()
                if not line:
                    return
                if len(line) > MAX_LINE_BYTES:
                    writer.write(
                        _encode({"ok": False, "error": {"code": "payload_too_large", "message": "line quá lớn"}})
                    )
                    await writer.drain()
                    continue
                try:
                    payload = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    writer.write(_encode({"ok": False, "error": {"code": "bad_json", "message": "JSON không hợp lệ"}}))
                    await writer.drain()
                    continue
                response = await self._dispatch(payload)
                writer.write(_encode(response))
                await writer.drain()
        except (TimeoutError, ConnectionError, asyncio.IncompleteReadError):
            return
        finally:
            with contextlib.suppress(ConnectionError):
                writer.close()

    async def _dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
        op = payload.get("op")
        try:
            if op == "open_session":
                view = await self._runtime.open_session(
                    run_id=UUID(payload["run_id"]),
                    attempt_id=UUID(payload["attempt_id"]),
                    session_key=payload["session_key"],
                    fence_epoch=int(payload.get("fence_epoch", 1)),
                    scene_version=int(payload.get("scene_version", 1)),
                )
                return {"ok": True, "result": view}
            if op == "execute":
                fields = {
                    key: payload[key]
                    for key in (
                        "command_id",
                        "session_key",
                        "run_id",
                        "attempt_id",
                        "fence_epoch",
                        "control_revision",
                        "expected_observation_version",
                        "operation",
                        "payload",
                        "side_effect",
                    )
                    if key in payload
                }
                receipt = await self._runtime.execute(CommandRequest.model_validate(fields))
                return {"ok": True, "result": receipt.as_dict()}
            if op == "heartbeat":
                alive = await self._runtime.heartbeat(payload["session_key"])
                return {"ok": True, "result": {"alive": alive}}
            if op == "close_session":
                view = await self._runtime.close_session(
                    payload["session_key"],
                    reason=payload.get("reason", "closed"),
                    quarantine=bool(payload.get("quarantine", False)),
                )
                return {"ok": True, "result": view}
            if op == "apply_control":
                result = await self._runtime.apply_control(UUID(payload["control_id"]))
                return {"ok": True, "result": result}
            if op == "receipts":
                receipts = await self._runtime.receipts(UUID(payload["attempt_id"]))
                return {"ok": True, "result": {"receipts": receipts}}
            if op == "session_view":
                view = await self._runtime.session_view(payload["session_key"])
                return {"ok": True, "result": view}
            if op == "run_execution":
                if self._coordinator is None:
                    return {"ok": False, "error": {"code": "coordinator_missing", "message": "chưa cấu hình"}}
                spec = ExecutionSpec(
                    workspace_id=UUID(payload["workspace_id"]),
                    principal_id=UUID(payload["principal_id"]),
                    run_id=UUID(payload["run_id"]),
                    execution_id=UUID(payload["execution_id"]),
                    attempt_id=UUID(payload["attempt_id"]),
                    logical_key=payload["logical_key"],
                    case=CaseContent.model_validate(payload["case"]),
                    target_base_url=payload["target_base_url"],
                    fixture_ref=payload["fixture_ref"],
                    namespace=payload["namespace"],
                    parameters=dict(payload.get("parameters", {})),
                    gate_profile=payload.get("gate_profile", "strict"),
                    fence_epoch=int(payload.get("fence_epoch", 1)),
                )
                outcome = await self._coordinator.execute(spec)
                return {"ok": True, "result": outcome_to_dict(outcome)}
            return {"ok": False, "error": {"code": "unknown_op", "message": str(op)}}
        except Exception as exc:
            return {"ok": False, "error": {"code": type(exc).__name__, "message": str(exc)}}


def _encode(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
