from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import ProviderRoute
from agentqa.contracts.values import SensitiveValue
from agentqa.platform.security.grants import GrantPurpose, GrantService, SecretGrant
from agentqa.platform.security.taint import SecurityError

pytestmark = pytest.mark.asyncio

GO_ENDPOINT = "https://opencode.ai/zen/go/v1"
ZEN_ENDPOINT = "https://opencode.ai/zen/v1"
CANARY = "synthetic-provider-key-canary"
FUTURE = datetime.now(UTC) + timedelta(hours=1)
PAST = datetime.now(UTC) - timedelta(hours=1)


def make_grant(**overrides) -> SecretGrant:
    values = {
        "id": uuid4(),
        "workspace_id": uuid4(),
        "credential_id": uuid4(),
        "credential_version": 1,
        "principal": str(uuid4()),
        "purpose": GrantPurpose.PROVIDER_AUTH_HEADER,
        "destination": GO_ENDPOINT,
        "target_identity": None,
        "expires_at": FUTURE,
        "revoked_at": None,
    }
    values.update(overrides)
    return SecretGrant(**values)


def make_service(seen: list[SecretGrant] | None = None, value: str = CANARY) -> GrantService:
    async def resolver(grant: SecretGrant) -> SensitiveValue:
        if seen is not None:
            seen.append(grant)
        return SensitiveValue(value)

    return GrantService(
        resolver=resolver,
        provider_origins={ProviderRoute.OPENCODE_GO: GO_ENDPOINT, ProviderRoute.OPENCODE_ZEN: ZEN_ENDPOINT},
    )


async def test_provider_header_grant_scoped_to_route_and_endpoint() -> None:
    seen: list[SecretGrant] = []
    service = make_service(seen)
    grant = make_grant()
    value = await service.authorize_provider_header(grant, route=ProviderRoute.OPENCODE_GO, origin=GO_ENDPOINT)
    assert value.reveal() == CANARY
    assert seen == [grant]

    with pytest.raises(SecurityError) as wrong_route:
        await service.authorize_provider_header(grant, route=ProviderRoute.OPENCODE_ZEN, origin=ZEN_ENDPOINT)
    assert wrong_route.value.code is ErrorCode.PERMISSION_DENIED
    with pytest.raises(SecurityError):
        await service.authorize_provider_header(grant, route=ProviderRoute.OPENCODE_GO, origin="https://evil.example")
    with pytest.raises(SecurityError):
        await service.authorize_provider_header(
            make_grant(destination=ZEN_ENDPOINT), route=ProviderRoute.OPENCODE_GO, origin=GO_ENDPOINT
        )
    assert len(seen) == 1


async def test_grant_expiry_revocation_and_purpose() -> None:
    service = make_service()
    with pytest.raises(SecurityError):
        await service.authorize_provider_header(
            make_grant(expires_at=PAST), route=ProviderRoute.OPENCODE_GO, origin=GO_ENDPOINT
        )
    with pytest.raises(SecurityError):
        await service.authorize_provider_header(
            make_grant(revoked_at=datetime.now(UTC)), route=ProviderRoute.OPENCODE_GO, origin=GO_ENDPOINT
        )
    with pytest.raises(SecurityError):
        await service.authorize_provider_header(
            make_grant(purpose=GrantPurpose.BROWSER_FILL), route=ProviderRoute.OPENCODE_GO, origin=GO_ENDPOINT
        )


async def test_fill_grant_requires_verified_target_and_context() -> None:
    service = make_service()
    grant = make_grant(
        purpose=GrantPurpose.BROWSER_FILL,
        destination="https://app.example.com/login#password",
        target_identity="ctx:login-password",
    )
    value = await service.authorize_fill_target(
        grant,
        target_identity="https://app.example.com/login#password",
        context_key="ctx:login-password",
    )
    assert value.reveal() == CANARY
    with pytest.raises(SecurityError):
        await service.authorize_fill_target(
            grant, target_identity="https://evil.example/login", context_key="ctx:login-password"
        )
    with pytest.raises(SecurityError):
        await service.authorize_fill_target(
            grant, target_identity="https://app.example.com/login#password", context_key="ctx:other"
        )


async def test_resolver_failure_does_not_leak_value() -> None:
    async def failing_resolver(grant: SecretGrant) -> SensitiveValue:
        raise RuntimeError(f"upstream rejected key {CANARY}")

    service = GrantService(
        resolver=failing_resolver,
        provider_origins={ProviderRoute.OPENCODE_GO: GO_ENDPOINT},
    )
    with pytest.raises(SecurityError) as error:
        await service.authorize_provider_header(make_grant(), route=ProviderRoute.OPENCODE_GO, origin=GO_ENDPOINT)
    assert CANARY not in str(error.value)
    assert CANARY not in repr(error.value)


async def test_sensitive_value_repr_and_serialization_fail_safe() -> None:
    value = SensitiveValue(CANARY)
    assert CANARY not in repr(value)
    assert CANARY not in str(value)
    with pytest.raises(TypeError):
        json.dumps(value)
    with pytest.raises(TypeError):
        json.dumps([value])
