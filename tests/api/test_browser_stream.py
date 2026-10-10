from __future__ import annotations

import json
import socket
import threading
from typing import Any

from agentqa.platform.frames import FrameEndpoint, SupervisorFrameClient


class FakeSupervisorSocket:
    def __init__(self, token: str, frames: dict[str, dict[str, Any]]) -> None:
        self._token = token
        self._frames = frames
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(2)
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            connection, _ = self._server.accept()
        except OSError:
            return
        with connection, connection.makefile("rwb") as stream:
            hello = json.loads(stream.readline().decode("utf-8"))
            if hello.get("token") != self._token:
                stream.write((json.dumps({"ok": False}) + "\n").encode("utf-8"))
                stream.flush()
                return
            stream.write((json.dumps({"ok": True, "result": {"supervisor_id": "fake"}}) + "\n").encode("utf-8"))
            stream.flush()
            request = json.loads(stream.readline().decode("utf-8"))
            frame = self._frames.get(request.get("session_key"))
            stream.write((json.dumps({"ok": True, "result": {"frame": frame}}) + "\n").encode("utf-8"))
            stream.flush()

    def close(self) -> None:
        self._server.close()


def test_frame_client_parses_frame_and_returns_none_for_unknown_session() -> None:
    server = FakeSupervisorSocket(
        token="secret-token",
        frames={
            "run-1": {
                "seq": 7,
                "viewport": {"width": 1280, "height": 720},
                "dpr": 1.0,
                "png_b64": "iVBORw0KGgo=",
            }
        },
    )
    try:
        client = SupervisorFrameClient(FrameEndpoint(host="127.0.0.1", port=server.port, token="secret-token"))
        import asyncio

        frame = asyncio.run(client.latest_frame("run-1"))
        assert frame is not None
        assert frame["seq"] == 7
        assert frame["media_type"] == "image/png"
        assert frame["png_b64"].startswith("iVBOR")

        missing = asyncio.run(client.latest_frame("run-unknown"))
        assert missing is None
    finally:
        server.close()


def test_frame_client_returns_none_when_supervisor_unreachable() -> None:
    import asyncio

    client = SupervisorFrameClient(FrameEndpoint(host="127.0.0.1", port=1, token="x"), timeout=1.0)
    assert asyncio.run(client.latest_frame("run-1")) is None
