from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx

from agentqa.contracts.case import FixtureReceipt
from agentqa.platform.fixtures.definitions import TASKBOARD_FIXTURE, FixtureDefinition

SYNTHETIC_USERS = ("alice", "bob")
CONTROL_HEADER = "x-taskboard-control"


def synthetic_password(namespace: str, username: str) -> str:
    material = f"taskboard-synthetic:{namespace}:{username}".encode()
    return "tb-" + hashlib.sha256(material).hexdigest()[:20]


def synthetic_accounts(namespace: str) -> dict[str, str]:
    return {username: synthetic_password(namespace, username) for username in SYNTHETIC_USERS}


class TaskboardFixture:
    def __init__(
        self,
        base_url: str,
        control_token: str,
        definition: FixtureDefinition = TASKBOARD_FIXTURE,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.control_token = control_token
        self._definition = definition
        self._timeout = timeout

    def definition(self) -> FixtureDefinition:
        return self._definition

    def _control(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/_control{path}"
        with httpx.Client(timeout=self._timeout, headers={CONTROL_HEADER: self.control_token}) as client:
            response = client.request(method, url, json=payload)
        response.raise_for_status()
        return response.json()

    def version(self) -> dict[str, Any]:
        return self._control("GET", "/version")

    def prepare(self, namespace: str, seed: str | None = None) -> FixtureReceipt:
        actual_seed = seed or self._definition.default_seed
        seed_spec = self._definition.seeds.get(actual_seed)
        if seed_spec is None:
            return FixtureReceipt(
                fixture_ref=self._definition.ref(),
                namespace=namespace,
                action="prepare",
                ok=False,
                detail=f"seed '{actual_seed}' không tồn tại",
            )
        payload = {
            "accounts": synthetic_accounts(namespace),
            "items": seed_spec.get("items", []),
            "duplicate_policy": seed_spec.get("duplicate_policy", "allow"),
        }
        state = self._control("POST", f"/namespaces/{namespace}/prepare", payload)
        detail = json.dumps(
            {
                "definition": self._definition.ref(),
                "fixture_digest": self._definition.digest(),
                "seed": actual_seed,
                "revision": state.get("revision"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return FixtureReceipt(
            fixture_ref=self._definition.ref(),
            namespace=namespace,
            action="prepare",
            ok=True,
            detail=detail,
        )

    def reset(self, namespace: str) -> FixtureReceipt:
        try:
            state = self._control("POST", f"/namespaces/{namespace}/reset")
        except httpx.HTTPStatusError as exc:
            return FixtureReceipt(
                fixture_ref=self._definition.ref(),
                namespace=namespace,
                action="reset",
                ok=False,
                detail=f"http {exc.response.status_code}",
            )
        return FixtureReceipt(
            fixture_ref=self._definition.ref(),
            namespace=namespace,
            action="reset",
            ok=True,
            detail=json.dumps({"revision": state.get("revision")}, sort_keys=True),
        )

    def cleanup(self, namespace: str) -> FixtureReceipt:
        result = self._control("POST", f"/namespaces/{namespace}/cleanup")
        return FixtureReceipt(
            fixture_ref=self._definition.ref(),
            namespace=namespace,
            action="cleanup",
            ok=True,
            detail=json.dumps({"removed": result.get("removed")}, sort_keys=True),
        )

    def probe(self, namespace: str) -> dict[str, Any]:
        return self._control("GET", f"/namespaces/{namespace}/probe")

    def state(self, namespace: str) -> dict[str, Any]:
        return self._control("GET", f"/namespaces/{namespace}/state")
