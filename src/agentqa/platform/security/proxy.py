from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field

from agentqa.platform.security.egress import EgressDenied, EgressPolicy

DENIED_RESPONSE = (
    "HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain; charset=utf-8\r\n"
    "Content-Length: 0\r\nConnection: close\r\n\r\n"
)


@dataclass
class EgressProxy:
    policy: EgressPolicy
    host: str = "127.0.0.1"
    port: int = 0
    _server: asyncio.AbstractServer | None = field(default=None, init=False, repr=False)
    requests: list[str] = field(default_factory=list)

    async def start(self) -> str:
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        socket = self._server.sockets[0]
        self.port = socket.getsockname()[1]
        return self.url

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            header_block = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
        except (TimeoutError, asyncio.IncompleteReadError):
            writer.close()
            return
        text = header_block.decode("latin-1")
        lines = text.split("\r\n")
        request_line = lines[0]
        parts = request_line.split(" ")
        if len(parts) != 3:
            writer.write(DENIED_RESPONSE.encode("latin-1"))
            await writer.drain()
            writer.close()
            return
        method, target, _version = parts
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                name, _, value = line.partition(":")
                headers[name.strip().lower()] = value.strip()
        if method.upper() == "CONNECT":
            await self._handle_connect(target, reader, writer)
        else:
            await self._handle_http(method, target, headers, reader, writer)

    async def _handle_connect(self, target: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        host, _, port_text = target.partition(":")
        self.requests.append(f"CONNECT {target}")
        try:
            endpoint = self.policy.check_connect(host, int(port_text or "443"))
        except (EgressDenied, ValueError):
            writer.write(DENIED_RESPONSE.encode("latin-1"))
            await writer.drain()
            writer.close()
            return
        upstream_host = endpoint.addresses[0]
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(upstream_host, endpoint.port)
        except OSError:
            writer.write(DENIED_RESPONSE.encode("latin-1"))
            await writer.drain()
            writer.close()
            return
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await self._pipe(reader, writer, upstream_reader, upstream_writer)

    async def _handle_http(
        self,
        method: str,
        target: str,
        headers: dict[str, str],
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.requests.append(f"{method} {target}")
        try:
            endpoint = self.policy.check_url(target)
        except EgressDenied:
            writer.write(DENIED_RESPONSE.encode("latin-1"))
            await writer.drain()
            writer.close()
            return
        content_length = int(headers.get("content-length", "0") or "0")
        body = await reader.readexactly(content_length) if content_length else b""
        from urllib.parse import urlsplit

        parts = urlsplit(target)
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        upstream_host = endpoint.addresses[0]
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(upstream_host, endpoint.port)
        except OSError:
            writer.write(DENIED_RESPONSE.encode("latin-1"))
            await writer.drain()
            writer.close()
            return
        forwarded = [f"{method} {path} HTTP/1.1"]
        for name, value in headers.items():
            if name in ("proxy-connection",):
                continue
            forwarded.append(f"{name}: {value}")
        forwarded.append("connection: close")
        upstream_writer.write(("\r\n".join(forwarded) + "\r\n\r\n").encode("latin-1"))
        if body:
            upstream_writer.write(body)
        await upstream_writer.drain()
        await self._pipe(reader, writer, upstream_reader, upstream_writer)

    async def _pipe(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        upstream_reader: asyncio.StreamReader,
        upstream_writer: asyncio.StreamWriter,
    ) -> None:
        async def forward(source: asyncio.StreamReader, sink: asyncio.StreamWriter) -> None:
            try:
                while True:
                    chunk = await source.read(65536)
                    if not chunk:
                        break
                    sink.write(chunk)
                    await sink.drain()
            except (ConnectionError, asyncio.IncompleteReadError):
                pass
            finally:
                with contextlib.suppress(ConnectionError):
                    sink.close()

        await asyncio.gather(
            forward(reader, upstream_writer),
            forward(upstream_reader, writer),
            return_exceptions=True,
        )
