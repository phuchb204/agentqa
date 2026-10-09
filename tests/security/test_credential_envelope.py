from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from agentqa.platform.security.credentials import (
    AES_GCM_ALGORITHM,
    CredentialService,
    EnvelopeError,
    EnvelopeService,
    MasterKeyring,
    NonceCollisionError,
    NonceRegistry,
)
from agentqa.platform.security.taint import SecurityError
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API
from tests.support.postgres import scoped_transaction, seed_workspace

pytestmark = pytest.mark.asyncio

CANARY = "canary-credential-value-7f3a"


def scripted_source(values: list[bytes]):
    iterator = iter(values)
    return lambda: next(iterator)


def _open(service: EnvelopeService, sealed, *, workspace_id: UUID, credential_id: UUID, version: int):
    return service.open_with_record(
        workspace_id=workspace_id,
        credential_id=credential_id,
        version=version,
        master_key_version=sealed.master_key_version,
        wrap_nonce=sealed.wrap_nonce,
        wrapped_data_key=sealed.wrapped_data_key,
        value_nonce=sealed.value_nonce,
        ciphertext=sealed.ciphertext,
    )


async def test_envelope_roundtrip_and_wrong_aad() -> None:
    service = EnvelopeService(MasterKeyring.synthetic())
    workspace_id, credential_id = uuid4(), uuid4()
    sealed = service.seal(workspace_id=workspace_id, credential_id=credential_id, version=1, plaintext=CANARY)
    assert sealed.algorithm == AES_GCM_ALGORITHM
    value = _open(service, sealed, workspace_id=workspace_id, credential_id=credential_id, version=1)
    assert value.reveal() == CANARY

    with pytest.raises(EnvelopeError):
        _open(service, sealed, workspace_id=uuid4(), credential_id=credential_id, version=1)
    with pytest.raises(EnvelopeError):
        _open(service, sealed, workspace_id=workspace_id, credential_id=uuid4(), version=1)
    with pytest.raises(EnvelopeError):
        _open(service, sealed, workspace_id=workspace_id, credential_id=credential_id, version=2)

    tampered = bytearray(sealed.ciphertext)
    tampered[0] ^= 0x01
    sealed_tampered = sealed.__class__(
        algorithm=sealed.algorithm,
        master_key_version=sealed.master_key_version,
        wrap_nonce=sealed.wrap_nonce,
        wrapped_data_key=sealed.wrapped_data_key,
        value_nonce=sealed.value_nonce,
        ciphertext=bytes(tampered),
        aad=sealed.aad,
    )
    with pytest.raises(EnvelopeError):
        _open(service, sealed_tampered, workspace_id=workspace_id, credential_id=credential_id, version=1)


async def test_nonce_registry_detects_collision() -> None:
    registry = NonceRegistry()
    nonce = b"0" * 12
    registry.register(1, nonce)
    with pytest.raises(NonceCollisionError):
        registry.register(1, nonce)
    registry.register(2, nonce)


async def test_envelope_record_never_stores_plaintext_or_master_key(runtime, role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    async with scoped_transaction(runtime.engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        record = await runtime.credentials.create_envelope(
            session, workspace_id=workspace, credential_ref="provider/main", plaintext=CANARY, actor="owner"
        )
        value = await runtime.credentials.resolve(
            session, workspace_id=workspace, credential_id=record.credential_id, version=record.version
        )
        assert value.reveal() == CANARY
        metadata = await runtime.credentials.public_metadata(
            session, workspace_id=workspace, credential_id=record.credential_id
        )
        assert CANARY not in str(metadata)
        row = (
            await session.execute(
                sa.select(tables.credential_records).where(tables.credential_records.c.id == record.credential_id)
            )
        ).one()
        audits = (
            await session.execute(sa.select(tables.audit_events.c.event_metadata, tables.audit_events.c.action))
        ).all()

    assert row.kind == "envelope"
    assert row.algorithm == AES_GCM_ALGORITHM
    assert row.aad == f"{workspace}:{record.credential_id}:{record.version}"
    assert CANARY.encode("utf-8") not in bytes(row.ciphertext)
    master_key = runtime.envelope.keyring.key(1)
    assert master_key != bytes(row.wrapped_data_key)
    assert master_key not in bytes(row.wrapped_data_key)
    assert len(runtime.envelope.keyring.key(row.master_key_version)) == 32
    assert audits
    assert all(CANARY not in str(metadata) for metadata, _action in audits)


async def test_env_reference_has_no_value_and_cannot_resolve(runtime, role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    async with scoped_transaction(runtime.engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        record = await runtime.credentials.create_env_reference(
            session,
            workspace_id=workspace,
            credential_ref="local/jev",
            env_var_name="AGENTQA_JEV_API_KEY",
            actor="owner",
        )
        assert record.kind == "env_ref"
        with pytest.raises(SecurityError):
            await runtime.credentials.resolve(
                session, workspace_id=workspace, credential_id=record.credential_id, version=record.version
            )
        metadata = await runtime.credentials.public_metadata(
            session, workspace_id=workspace, credential_id=record.credential_id
        )
    assert metadata["kind"] == "env_ref"
    assert "value" not in metadata


async def test_rotation_creates_new_version_and_pins(runtime, role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    async with scoped_transaction(runtime.engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        first = await runtime.credentials.create_envelope(
            session, workspace_id=workspace, credential_ref="provider/main", plaintext="value-one", actor="owner"
        )
        second = await runtime.credentials.rotate(
            session, workspace_id=workspace, credential_ref="provider/main", plaintext="value-two", actor="owner"
        )
        assert second.version == first.version + 1
        assert second.credential_id != first.credential_id
        first_value = await runtime.credentials.resolve(
            session, workspace_id=workspace, credential_id=first.credential_id, version=first.version
        )
        second_value = await runtime.credentials.resolve(
            session, workspace_id=workspace, credential_id=second.credential_id, version=second.version
        )
        assert first_value.reveal() == "value-one"
        assert second_value.reveal() == "value-two"
        row = (
            await session.execute(
                sa.select(tables.credential_records.c.rotated_from).where(
                    tables.credential_records.c.id == second.credential_id
                )
            )
        ).scalar_one()
        assert row == first.credential_id


async def test_nonce_collision_across_records_blocks_write(runtime, role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    source = scripted_source([b"a" * 12, b"b" * 12, b"a" * 12, b"c" * 12])
    credentials = CredentialService(EnvelopeService(runtime.envelope.keyring, nonce_source=source))
    async with scoped_transaction(runtime.engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        await credentials.create_envelope(
            session, workspace_id=workspace, credential_ref="provider/collision", plaintext="one", actor="owner"
        )
    with pytest.raises(NonceCollisionError):
        async with scoped_transaction(
            runtime.engines[ROLE_API], principal_id=principal, workspace_id=workspace
        ) as session:
            await credentials.create_envelope(
                session, workspace_id=workspace, credential_ref="provider/collision", plaintext="two", actor="owner"
            )
    async with scoped_transaction(runtime.engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        count = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(tables.credential_records)
                .where(tables.credential_records.c.credential_ref == "provider/collision")
            )
        ).scalar_one()
    assert count == 1


async def test_deleted_record_registry_keeps_nonce_reserved(runtime, role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    source = scripted_source([b"w" * 12, b"v" * 12, b"x" * 12, b"y" * 12, b"w" * 12, b"z" * 12])
    credentials = CredentialService(EnvelopeService(runtime.envelope.keyring, nonce_source=source))
    async with scoped_transaction(runtime.engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        first = await credentials.create_envelope(
            session, workspace_id=workspace, credential_ref="provider/deleted", plaintext="one", actor="owner"
        )
        second = await credentials.create_envelope(
            session, workspace_id=workspace, credential_ref="provider/deleted", plaintext="two", actor="owner"
        )
        await credentials.soft_delete(
            session, workspace_id=workspace, credential_id=second.credential_id, actor="owner"
        )
        assert first.credential_id != second.credential_id
    with pytest.raises(NonceCollisionError):
        async with scoped_transaction(
            runtime.engines[ROLE_API], principal_id=principal, workspace_id=workspace
        ) as session:
            await credentials.create_envelope(
                session, workspace_id=workspace, credential_ref="provider/deleted", plaintext="three", actor="owner"
            )
