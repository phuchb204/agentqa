from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa

from agentqa.platform.security.credentials import CredentialService, EnvelopeService, MasterKeyring
from agentqa.platform.security.grants import GrantPurpose, GrantService, SecretGrant
from agentqa.platform.security.taint import SecurityError
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API
from tests.support.postgres import scoped_transaction, seed_workspace
from tests.support.security import create_user, create_workspace, csrf_headers, login

pytestmark = pytest.mark.asyncio

GATEWAY_ORIGIN = "https://opencode.ai/zen/go/v1"


def _service() -> CredentialService:
    return CredentialService(EnvelopeService(MasterKeyring.synthetic()))


async def _grant_row(engines, workspace_id, principal_id, credential_id, version):
    async with scoped_transaction(engines[ROLE_API], principal_id=principal_id, workspace_id=workspace_id) as session:
        await session.execute(
            sa.insert(tables.credential_grants).values(
                workspace_id=workspace_id,
                credential_id=credential_id,
                credential_version=version,
                principal=str(principal_id),
                purpose="provider_auth_header",
                destination=GATEWAY_ORIGIN,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        row = (
            await session.execute(
                sa.select(tables.credential_grants).where(tables.credential_grants.c.credential_id == credential_id)
            )
        ).one()
    return SecretGrant(
        id=row.id,
        workspace_id=row.workspace_id,
        credential_id=row.credential_id,
        credential_version=row.credential_version,
        principal=row.principal,
        purpose=GrantPurpose(row.purpose),
        destination=row.destination,
        target_identity=row.target_identity,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


async def test_rotate_retires_old_version_and_revokes_grants(role_engines) -> None:
    engines = role_engines
    user_id, workspace_id = await seed_workspace(engines, label=f"cred-{uuid4().hex[:8]}")
    service = _service()
    async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
        first = await service.create_envelope(
            session, workspace_id=workspace_id, credential_ref="opencode_go", plaintext="sk-secret-one", actor="t"
        )
    grant = await _grant_row(engines, workspace_id, user_id, first.credential_id, first.version)

    async def _unused_resolver(_grant):
        raise AssertionError("resolver không được gọi trong kiểm tra thu hồi")

    grants = GrantService(resolver=_unused_resolver, provider_origins={})
    assert grant.revoked_at is None

    async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
        second = await service.rotate(
            session, workspace_id=workspace_id, credential_ref="opencode_go", plaintext="sk-secret-two", actor="t"
        )
    assert second.version == first.version + 1

    async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
        rows = (
            await session.execute(
                sa.select(tables.credential_records.c.id, tables.credential_records.c.status).where(
                    tables.credential_records.c.credential_ref == "opencode_go"
                )
            )
        ).all()
        old_grant = (
            await session.execute(
                sa.select(tables.credential_grants.c.revoked_at, tables.credential_grants.c.revoke_reason).where(
                    tables.credential_grants.c.credential_id == first.credential_id
                )
            )
        ).one()
    statuses = {row.id: row.status for row in rows}
    assert statuses[first.credential_id] == "rotated"
    assert statuses[second.credential_id] == "active"
    assert old_grant.revoked_at is not None
    assert old_grant.revoke_reason == "credential_rotated"

    revoked_grant = replace(grant, revoked_at=old_grant.revoked_at)
    with pytest.raises(SecurityError):
        await grants.authorize_provider_header(
            revoked_grant,
            route=_go_route(),
            origin=GATEWAY_ORIGIN,
        )

    async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
        with pytest.raises(SecurityError):
            await service.resolve(
                session,
                workspace_id=workspace_id,
                credential_id=first.credential_id,
                version=first.version,
            )
        value = await service.resolve(
            session,
            workspace_id=workspace_id,
            credential_id=second.credential_id,
            version=second.version,
        )
        assert value.reveal() == "sk-secret-two"


def _go_route():
    from agentqa.contracts.models import ProviderRoute

    return ProviderRoute.OPENCODE_GO


async def test_revoke_reference_invalidates_all_active_versions(role_engines) -> None:
    engines = role_engines
    user_id, workspace_id = await seed_workspace(engines, label=f"cred-{uuid4().hex[:8]}")
    service = _service()
    async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
        first = await service.create_envelope(
            session, workspace_id=workspace_id, credential_ref="opencode_zen", plaintext="sk-a", actor="t"
        )
        second = await service.rotate(
            session, workspace_id=workspace_id, credential_ref="opencode_zen", plaintext="sk-b", actor="t"
        )
        count = await service.revoke_reference(
            session, workspace_id=workspace_id, credential_ref="opencode_zen", reason="leaked", actor="t"
        )
    assert count == 1
    assert second.status == "active"
    async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
        rows = (
            await session.execute(
                sa.select(tables.credential_records.c.id, tables.credential_records.c.status).where(
                    tables.credential_records.c.credential_ref == "opencode_zen"
                )
            )
        ).all()
        revoked_versions = {row.id: row.status for row in rows}
    assert revoked_versions[first.credential_id] == "rotated"
    assert revoked_versions[second.credential_id] == "revoked"


async def _owner_workspace(api_client, runtime):
    _user_id, username = await create_user(runtime, "owner", "pw-123456")
    csrf = await login(api_client, username, "pw-123456")
    workspace_id = await create_workspace(api_client, csrf, f"ws-{uuid4().hex[:6]}")
    return workspace_id, csrf


async def test_credential_reference_api_no_plaintext_read(api_client, runtime) -> None:
    workspace_id, csrf = await _owner_workspace(api_client, runtime)
    created = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/credential-references",
        json={"credential_ref": "opencode_go", "env_var_name": "OPENCODE_GO_KEY"},
        headers=csrf_headers(csrf),
    )
    assert created.status_code == 200, created.text
    assert created.json()["version"] == 1
    rotated = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/credential-references/opencode_go/rotate",
        json={"value": "sk-super-secret-value"},
        headers=csrf_headers(csrf),
    )
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["version"] == 2
    listed = await api_client.get(f"/api/v1/workspaces/{workspace_id}/credential-references")
    assert listed.status_code == 200, listed.text
    body = listed.text
    assert "sk-super-secret-value" not in body
    items = listed.json()["items"]
    versions = {(item["version"], item["status"]) for item in items}
    assert (1, "rotated") in versions
    assert (2, "active") in versions
    revoked = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/credential-references/opencode_go/revoke",
        json={"reason": "rotation policy"},
        headers=csrf_headers(csrf),
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["revoked_versions"] == 1
    relisted = await api_client.get(f"/api/v1/workspaces/{workspace_id}/credential-references")
    statuses = {(item["version"], item["status"]) for item in relisted.json()["items"]}
    assert (2, "revoked") in statuses


async def test_credential_api_requires_owner(api_client, runtime) -> None:
    workspace_id, csrf = await _owner_workspace(api_client, runtime)
    _viewer_id, viewer_name = await create_user(runtime, "viewer", "pw-123456")
    added = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/memberships",
        json={"username": viewer_name, "role": "viewer"},
        headers=csrf_headers(csrf),
    )
    assert added.status_code == 200, added.text
    viewer_csrf = await login(api_client, viewer_name, "pw-123456")
    denied = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/credential-references",
        json={"credential_ref": "x", "env_var_name": "X"},
        headers=csrf_headers(viewer_csrf),
    )
    assert denied.status_code == 403
    hidden = await api_client.get(f"/api/v1/workspaces/{workspace_id}/credential-references")
    assert hidden.status_code == 403
