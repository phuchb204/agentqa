from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa

from agentqa.contracts.models import ProviderRoute
from agentqa.platform.identity.models import IdentityError, Role
from agentqa.platform.security.grants import GrantPurpose, SecretGrant
from agentqa.platform.security.taint import SecurityError
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API
from tests.support.postgres import scoped_transaction, seed_workspace

pytestmark = pytest.mark.asyncio

GO_ENDPOINT = "https://opencode.ai/zen/go/v1"
FUTURE = datetime.now(UTC) + timedelta(hours=1)


def grant_for(*, workspace_id, credential_id, version: int, principal: str) -> SecretGrant:
    return SecretGrant(
        id=uuid4(),
        workspace_id=workspace_id,
        credential_id=credential_id,
        credential_version=version,
        principal=principal,
        purpose=GrantPurpose.PROVIDER_AUTH_HEADER,
        destination=GO_ENDPOINT,
        target_identity=None,
        expires_at=FUTURE,
    )


async def test_revoked_credential_blocks_new_admission(runtime, role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    async with scoped_transaction(runtime.engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        first = await runtime.credentials.create_envelope(
            session, workspace_id=workspace, credential_ref="provider/main", plaintext="pinned-one", actor="owner"
        )
    grant_v1 = grant_for(
        workspace_id=workspace, credential_id=first.credential_id, version=first.version, principal=str(principal)
    )
    value = await runtime.grants.authorize_provider_header(
        grant_v1, route=ProviderRoute.OPENCODE_GO, origin=GO_ENDPOINT
    )
    assert value.reveal() == "pinned-one"

    async with scoped_transaction(runtime.engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        await runtime.credentials.revoke(
            session, workspace_id=workspace, credential_id=first.credential_id, reason="rotation", actor="owner"
        )

    with pytest.raises(SecurityError) as error:
        await runtime.grants.authorize_provider_header(grant_v1, route=ProviderRoute.OPENCODE_GO, origin=GO_ENDPOINT)
    assert "pinned-one" not in str(error.value)

    async with scoped_transaction(runtime.engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        second = await runtime.credentials.rotate(
            session, workspace_id=workspace, credential_ref="provider/main", plaintext="pinned-two", actor="owner"
        )
        assert second.credential_id != first.credential_id
    grant_v2 = grant_for(
        workspace_id=workspace, credential_id=second.credential_id, version=second.version, principal=str(principal)
    )
    value = await runtime.grants.authorize_provider_header(
        grant_v2, route=ProviderRoute.OPENCODE_GO, origin=GO_ENDPOINT
    )
    assert value.reveal() == "pinned-two"

    async with scoped_transaction(runtime.engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        audits = (
            await session.execute(
                sa.select(
                    tables.audit_events.c.action,
                    tables.audit_events.c.reason,
                    tables.audit_events.c.event_metadata,
                ).where(tables.audit_events.c.workspace_id == workspace)
            )
        ).all()
    actions = {row.action for row in audits}
    assert "credential.revoked" in actions
    assert sum(1 for row in audits if row.action in ("credential.create_envelope", "credential.rotate")) >= 2
    assert all("pinned-one" not in str(row.event_metadata) for row in audits)
    assert all("pinned-two" not in str(row.event_metadata) for row in audits)


async def test_grant_revocation_and_expiry_block_resolution(runtime, role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    async with scoped_transaction(runtime.engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        record = await runtime.credentials.create_envelope(
            session, workspace_id=workspace, credential_ref="provider/revoke", plaintext="value-x", actor="owner"
        )
    base = grant_for(
        workspace_id=workspace, credential_id=record.credential_id, version=record.version, principal=str(principal)
    )
    revoked = SecretGrant(
        id=base.id,
        workspace_id=base.workspace_id,
        credential_id=base.credential_id,
        credential_version=base.credential_version,
        principal=base.principal,
        purpose=base.purpose,
        destination=base.destination,
        target_identity=base.target_identity,
        expires_at=base.expires_at,
        revoked_at=datetime.now(UTC),
    )
    with pytest.raises(SecurityError):
        await runtime.grants.authorize_provider_header(revoked, route=ProviderRoute.OPENCODE_GO, origin=GO_ENDPOINT)
    expired = SecretGrant(
        id=base.id,
        workspace_id=base.workspace_id,
        credential_id=base.credential_id,
        credential_version=base.credential_version,
        principal=base.principal,
        purpose=base.purpose,
        destination=base.destination,
        target_identity=base.target_identity,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    with pytest.raises(SecurityError):
        await runtime.grants.authorize_provider_header(expired, route=ProviderRoute.OPENCODE_GO, origin=GO_ENDPOINT)


async def test_membership_change_invalidates_cached_permissions(runtime, role_engines: dict) -> None:
    owner, workspace = await seed_workspace(role_engines)
    member = await _second_user(runtime)
    async with scoped_transaction(runtime.engines[ROLE_API], principal_id=owner, workspace_id=workspace) as session:
        await session.execute(
            sa.insert(tables.memberships).values(workspace_id=workspace, user_id=member, role="editor")
        )
    from agentqa.platform.identity.models import Permission

    await runtime.authorization.require(workspace_id=workspace, user_id=member, permission=Permission.RUN_SUBMIT)
    assert runtime.authorization.cache.get(workspace, member) is not None
    await runtime.authorization.change_role(workspace_id=workspace, actor_id=owner, user_id=member, role=Role.VIEWER)
    assert runtime.authorization.cache.get(workspace, member) is None
    with pytest.raises(IdentityError):
        await runtime.authorization.require(workspace_id=workspace, user_id=member, permission=Permission.RUN_SUBMIT)


async def _second_user(runtime) -> object:
    user = await runtime.users.create(username=f"member-{uuid4().hex[:8]}", password="pw-123456")
    return user.id
