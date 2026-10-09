from __future__ import annotations

import os
import socket
from collections.abc import MutableMapping
from typing import Any

PROVIDER_ENV_VARS = (
    "AGENTQA_JEV_API_KEY",
    "AGENTQA_LLM_API_KEY",
)
LOCAL_HOSTS = (
    "127.0.0.1",
    "::1",
    "localhost",
)
ALLOWED_HOSTS_ENV = "AGENTQA_TEST_ALLOWED_HOSTS"
GUARD_ATTRIBUTE = "_agentqa_network_guard"


class NetworkGuardError(RuntimeError):
    pass


def is_provider_env_var(name: str) -> bool:
    return name.startswith("AGENTQA_") and name.endswith("_API_KEY")


def strip_provider_env(environ: MutableMapping[str, str] | None = None) -> list[str]:
    target = os.environ if environ is None else environ
    removed: list[str] = []
    for name in list(target):
        if is_provider_env_var(name):
            del target[name]
            removed.append(name)
    return removed


def sanitized_environment(environ: MutableMapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    return {name: value for name, value in source.items() if not is_provider_env_var(name)}


def declared_allowed_hosts() -> frozenset[str]:
    extra = os.environ.get(ALLOWED_HOSTS_ENV, "")
    declared = {item.strip().lower() for item in extra.split(",") if item.strip()}
    return frozenset(LOCAL_HOSTS) | frozenset(declared)


def normalized_host(address: object) -> str | None:
    if isinstance(address, (tuple, list)) and address:
        host: object = address[0]
    else:
        host = address
    if not isinstance(host, str):
        return None
    cleaned = host.strip().strip("[]").split("%", 1)[0].lower()
    return cleaned or None


def guard_host(host: str | None) -> None:
    if host is None:
        return
    if host in declared_allowed_hosts():
        return
    raise NetworkGuardError(
        f"Network guard blocked outbound connection to '{host}'. "
        f"Declare local fixture endpoints via {ALLOWED_HOSTS_ENV}."
    )


def install_network_guard() -> None:
    if getattr(socket.socket, GUARD_ATTRIBUTE, False):
        return
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        guard_host(normalized_host(address))
        return original_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> int:
        guard_host(normalized_host(address))
        return original_connect_ex(self, address)

    def guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
        guard_host(normalized_host(address))
        return original_create_connection(address, *args, **kwargs)

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        guard_host(host if isinstance(host, str) else None)
        return original_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.create_connection = guarded_create_connection
    socket.getaddrinfo = guarded_getaddrinfo
    setattr(socket.socket, GUARD_ATTRIBUTE, True)
