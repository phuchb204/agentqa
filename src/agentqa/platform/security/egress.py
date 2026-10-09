from __future__ import annotations

import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}
ALLOWED_SCHEMES = frozenset(DEFAULT_PORTS)
PRIVATE_PREFIXES = ("10.", "192.168.", "169.254.")


class EgressDenied(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"egress denied: {reason}")


@dataclass(frozen=True)
class AllowedEndpoint:
    host: str
    port: int
    addresses: tuple[str, ...] = ("127.0.0.1",)


@dataclass(frozen=True)
class EgressDecision:
    target: str
    allowed: bool
    reason: str


Resolver = Callable[[str], list[str]]


def system_resolver(host: str) -> list[str]:
    if host in ("127.0.0.1", "::1", "localhost"):
        return ["127.0.0.1"] if host != "::1" else ["::1"]
    infos = socket.getaddrinfo(host, None)
    return sorted({str(info[4][0]) for info in infos})


@dataclass
class EgressPolicy:
    endpoints: tuple[AllowedEndpoint, ...]
    resolver: Resolver = system_resolver
    decisions: list[EgressDecision] = field(default_factory=list)

    def __init__(self, endpoints: Iterable[AllowedEndpoint], resolver: Resolver = system_resolver) -> None:
        self.endpoints = tuple(endpoints)
        self.resolver = resolver
        self.decisions = []

    def _record(self, target: str, allowed: bool, reason: str) -> None:
        self.decisions.append(EgressDecision(target=target, allowed=allowed, reason=reason))

    def _match(self, host: str, port: int) -> AllowedEndpoint | None:
        for endpoint in self.endpoints:
            if endpoint.host == host and endpoint.port == port:
                return endpoint
        return None

    def _resolved_addresses(self, host: str, port: int) -> list[str]:
        if is_literal_address(host):
            return [host]
        try:
            return list(self.resolver(host))
        except OSError as exc:
            raise EgressDenied(f"DNS resolution thất bại cho {host}: {exc}") from exc

    def check_target(self, scheme: str, host: str, port: int, display: str) -> AllowedEndpoint:
        if scheme not in ALLOWED_SCHEMES:
            self._record(display, False, f"scheme '{scheme}' không được phép")
            raise EgressDenied(f"scheme '{scheme}' không được phép")
        endpoint = self._match(host, port)
        if endpoint is None:
            self._record(display, False, f"host:port {host}:{port} không nằm trong allowlist")
            raise EgressDenied(f"host:port {host}:{port} không nằm trong allowlist")
        addresses = self._resolved_addresses(host, port)
        unexpected = [address for address in addresses if address not in endpoint.addresses]
        if unexpected:
            self._record(display, False, f"địa chỉ resolve {unexpected} không khớp allowlist")
            raise EgressDenied(f"địa chỉ resolve {unexpected} không khớp allowlist")
        self._record(display, True, "allowed")
        return endpoint

    def check_url(self, url: str) -> AllowedEndpoint:
        parts = urlsplit(url)
        if not parts.scheme or not parts.hostname:
            self._record(url, False, "URL thiếu scheme/host")
            raise EgressDenied("URL thiếu scheme/host")
        port = parts.port or DEFAULT_PORTS.get(parts.scheme.lower(), 0)
        return self.check_target(parts.scheme.lower(), parts.hostname, port, url)

    def check_connect(self, host: str, port: int) -> AllowedEndpoint:
        return self.check_target("https", host, port, f"{host}:{port}")

    def check_redirect(self, to_url: str) -> AllowedEndpoint:
        return self.check_url(to_url)


def is_literal_address(host: str) -> bool:
    try:
        socket.inet_pton(socket.AF_INET, host)
        return True
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, host)
        return True
    except OSError:
        return False
