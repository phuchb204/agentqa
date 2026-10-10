from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
from dataclasses import dataclass
from typing import Any, Protocol


class BrowserFramePort(Protocol):
    async def latest_frame(self, session_key: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class FrameEndpoint:
    host: str
    port: int
    token: str

    @classmethod
    def from_environment(cls) -> FrameEndpoint | None:
        host = os.environ.get("AGENTQA_SUPERVISOR_HOST", "")
        port_text = os.environ.get("AGENTQA_SUPERVISOR_PORT", "")
        token = os.environ.get("AGENTQA_SUPERVISOR_TOKEN", "")
        if not host or not port_text or not token:
            return None
        try:
            port = int(port_text)
        except ValueError:
            return None
        return cls(host=host, port=port, token=token)


class SupervisorFrameClient:
    def __init__(self, endpoint: FrameEndpoint, *, timeout: float = 10.0) -> None:
        self._endpoint = endpoint
        self._timeout = timeout

    async def latest_frame(self, session_key: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._latest_frame_blocking, session_key)

    def _latest_frame_blocking(self, session_key: str) -> dict[str, Any] | None:
        try:
            with socket.create_connection((self._endpoint.host, self._endpoint.port), timeout=self._timeout) as sock:
                sock.settimeout(self._timeout)
                stream = sock.makefile("rwb")
                hello = self._exchange(stream, {"token": self._endpoint.token})
                if hello.get("ok") is not True:
                    return None
                response = self._exchange(stream, {"op": "latest_frame", "session_key": session_key})
        except OSError:
            return None
        if response.get("ok") is not True:
            return None
        frame = response.get("result", {}).get("frame")
        if not frame:
            return None
        return {
            "seq": int(frame.get("seq", 0)),
            "viewport": frame.get("viewport") or {},
            "dpr": float(frame.get("dpr", 1.0)),
            "media_type": "image/png",
            "png_b64": frame.get("png_b64", ""),
        }

    def _exchange(self, stream, payload: dict[str, Any]) -> dict[str, Any]:
        stream.write((json.dumps(payload) + "\n").encode("utf-8"))
        stream.flush()
        line = stream.readline()
        if not line:
            raise OSError("supervisor đóng kết nối")
        return json.loads(line.decode("utf-8"))


def encode_frame(png_bytes: bytes) -> str:
    return base64.b64encode(png_bytes).decode("ascii")
