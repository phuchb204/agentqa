from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.values import SensitiveValue
from agentqa.platform.security.taint import SecurityError
from agentqa.platform.storage import tables

DATA_KEY_BYTES = 32
NONCE_BYTES = 12
AES_GCM_ALGORITHM = "AES-256-GCM"


class NonceCollisionError(SecurityError):
    def __init__(self) -> None:
        super().__init__(ErrorCode.SECRET_SERIALIZATION, "Nonce đã tồn tại trong registry")


class EnvelopeError(SecurityError):
    def __init__(self) -> None:
        super().__init__(ErrorCode.SECRET_SERIALIZATION, "Envelope không giải mã được")


@dataclass(frozen=True)
class EncryptedEnvelope:
    algorithm: str
    master_key_version: int
    wrap_nonce: bytes
    wrapped_data_key: bytes
    value_nonce: bytes
    ciphertext: bytes
    aad: str


class MasterKeyring:
    def __init__(self, keys: dict[int, bytes], current_version: int) -> None:
        if current_version not in keys:
            raise ValueError("current_version phải nằm trong keyring")
        for version, key in keys.items():
            if len(key) != DATA_KEY_BYTES:
                raise ValueError(f"master key version {version} phải đủ 256-bit")
        self._keys = dict(keys)
        self.current_version = current_version

    @classmethod
    def synthetic(cls, label: str = "agentqa-master", version: int = 1) -> MasterKeyring:
        material = label.encode("utf-8")
        key = material.ljust(DATA_KEY_BYTES, b"0")[:DATA_KEY_BYTES]
        return cls({version: key}, current_version=version)

    def key(self, version: int) -> bytes:
        try:
            return self._keys[version]
        except KeyError as error:
            raise EnvelopeError() from error

    def with_new_version(self, version: int) -> MasterKeyring:
        keys = dict(self._keys)
        keys[version] = secrets.token_bytes(DATA_KEY_BYTES)
        return MasterKeyring(keys, current_version=version)


class NonceRegistry:
    def __init__(self) -> None:
        self._entries: set[tuple[int, bytes]] = set()

    def register(self, master_key_version: int, nonce: bytes) -> None:
        key = (master_key_version, nonce)
        if key in self._entries:
            raise NonceCollisionError()
        self._entries.add(key)


class DbNonceRegistry:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(
        self, master_key_version: int, nonce: bytes, *, credential_id: UUID, credential_version: int
    ) -> None:
        try:
            await self._session.execute(
                sa.insert(tables.credential_nonce_registry).values(
                    master_key_version=master_key_version,
                    nonce=nonce,
                    credential_id=credential_id,
                    credential_version=credential_version,
                )
            )
            await self._session.flush()
        except IntegrityError as error:
            raise NonceCollisionError() from error


class EnvelopeService:
    def __init__(
        self,
        keyring: MasterKeyring,
        nonce_source: Callable[[], bytes] | None = None,
        data_key_source: Callable[[], bytes] | None = None,
    ) -> None:
        self._keyring = keyring
        self._nonce_source = nonce_source or (lambda: secrets.token_bytes(NONCE_BYTES))
        self._data_key_source = data_key_source or (lambda: secrets.token_bytes(DATA_KEY_BYTES))

    @property
    def keyring(self) -> MasterKeyring:
        return self._keyring

    @staticmethod
    def aad(workspace_id: UUID, credential_id: UUID, version: int) -> bytes:
        return f"{workspace_id}:{credential_id}:{version}".encode()

    def seal(
        self,
        *,
        workspace_id: UUID,
        credential_id: UUID,
        version: int,
        plaintext: str | bytes,
    ) -> EncryptedEnvelope:
        payload = plaintext.encode("utf-8") if isinstance(plaintext, str) else plaintext
        aad = self.aad(workspace_id, credential_id, version)
        data_key = self._data_key_source()
        wrap_nonce = self._nonce_source()
        value_nonce = self._nonce_source()
        master = self._keyring.key(self._keyring.current_version)
        wrapped_data_key = AESGCM(master).encrypt(wrap_nonce, data_key, aad)
        ciphertext = AESGCM(data_key).encrypt(value_nonce, payload, aad)
        return EncryptedEnvelope(
            algorithm=AES_GCM_ALGORITHM,
            master_key_version=self._keyring.current_version,
            wrap_nonce=wrap_nonce,
            wrapped_data_key=wrapped_data_key,
            value_nonce=value_nonce,
            ciphertext=ciphertext,
            aad=aad.decode("utf-8"),
        )

    def open_with_record(
        self,
        *,
        workspace_id: UUID,
        credential_id: UUID,
        version: int,
        master_key_version: int,
        wrap_nonce: bytes,
        wrapped_data_key: bytes,
        value_nonce: bytes,
        ciphertext: bytes,
    ) -> SensitiveValue:
        aad = self.aad(workspace_id, credential_id, version)
        master = self._keyring.key(master_key_version)
        try:
            data_key = AESGCM(master).decrypt(wrap_nonce, wrapped_data_key, aad)
            plaintext = AESGCM(data_key).decrypt(value_nonce, ciphertext, aad)
        except InvalidTag as error:
            raise EnvelopeError() from error
        return SensitiveValue(plaintext.decode("utf-8"))


@dataclass(frozen=True)
class CredentialVersion:
    credential_id: UUID
    workspace_id: UUID
    credential_ref: str
    version: int
    kind: str
    status: str


class CredentialService:
    def __init__(self, envelope: EnvelopeService) -> None:
        self._envelope = envelope

    @property
    def envelope(self) -> EnvelopeService:
        return self._envelope

    async def _next_version(self, session: AsyncSession, *, workspace_id: UUID, credential_ref: str) -> int:
        current = (
            await session.execute(
                sa.select(sa.func.max(tables.credential_records.c.version)).where(
                    tables.credential_records.c.workspace_id == workspace_id,
                    tables.credential_records.c.credential_ref == credential_ref,
                )
            )
        ).scalar_one_or_none()
        return (current or 0) + 1

    async def create_env_reference(
        self, session: AsyncSession, *, workspace_id: UUID, credential_ref: str, env_var_name: str, actor: str
    ) -> CredentialVersion:
        version = await self._next_version(session, workspace_id=workspace_id, credential_ref=credential_ref)
        credential_id = uuid4()
        await session.execute(
            sa.insert(tables.credential_records).values(
                id=credential_id,
                workspace_id=workspace_id,
                credential_ref=credential_ref,
                version=version,
                kind="env_ref",
                status="active",
                env_var_name=env_var_name,
            )
        )
        await self._audit(
            session,
            workspace_id=workspace_id,
            actor=actor,
            action="credential.create_env_reference",
            subject_id=str(credential_id),
            reason=None,
            metadata={"version": version, "env_var_name": env_var_name},
        )
        return CredentialVersion(
            credential_id=credential_id,
            workspace_id=workspace_id,
            credential_ref=credential_ref,
            version=version,
            kind="env_ref",
            status="active",
        )

    async def create_envelope(
        self, session: AsyncSession, *, workspace_id: UUID, credential_ref: str, plaintext: str, actor: str
    ) -> CredentialVersion:
        version = await self._next_version(session, workspace_id=workspace_id, credential_ref=credential_ref)
        return await self._write_envelope(
            session,
            workspace_id=workspace_id,
            credential_ref=credential_ref,
            version=version,
            plaintext=plaintext,
            actor=actor,
            rotated_from=None,
        )

    async def rotate(
        self, session: AsyncSession, *, workspace_id: UUID, credential_ref: str, plaintext: str, actor: str
    ) -> CredentialVersion:
        version = await self._next_version(session, workspace_id=workspace_id, credential_ref=credential_ref)
        previous = (
            (
                await session.execute(
                    sa.select(tables.credential_records.c.id).where(
                        tables.credential_records.c.workspace_id == workspace_id,
                        tables.credential_records.c.credential_ref == credential_ref,
                        tables.credential_records.c.status == "active",
                    )
                )
            )
            .scalars()
            .all()
        )
        record = await self._write_envelope(
            session,
            workspace_id=workspace_id,
            credential_ref=credential_ref,
            version=version,
            plaintext=plaintext,
            actor=actor,
            rotated_from=previous[0] if previous else None,
        )
        if previous:
            await session.execute(
                sa.update(tables.credential_records)
                .where(
                    tables.credential_records.c.workspace_id == workspace_id,
                    tables.credential_records.c.id.in_(list(previous)),
                )
                .values(status="rotated")
            )
            await self._revoke_grants(
                session, workspace_id=workspace_id, credential_ids=list(previous), reason="credential_rotated"
            )
            await self._audit(
                session,
                workspace_id=workspace_id,
                actor=actor,
                action="credential.retire_rotated_versions",
                subject_id=str(record.credential_id),
                reason=None,
                metadata={"retired_versions": [str(item) for item in previous], "new_version": version},
            )
        return record

    async def revoke_reference(
        self, session: AsyncSession, *, workspace_id: UUID, credential_ref: str, reason: str, actor: str
    ) -> int:
        active_ids = (
            (
                await session.execute(
                    sa.select(tables.credential_records.c.id).where(
                        tables.credential_records.c.workspace_id == workspace_id,
                        tables.credential_records.c.credential_ref == credential_ref,
                        tables.credential_records.c.status == "active",
                    )
                )
            )
            .scalars()
            .all()
        )
        if not active_ids:
            raise SecurityError(ErrorCode.NOT_FOUND, "Không tìm thấy credential reference đang active")
        await session.execute(
            sa.update(tables.credential_records)
            .where(
                tables.credential_records.c.workspace_id == workspace_id,
                tables.credential_records.c.id.in_(list(active_ids)),
            )
            .values(status="revoked", revoked_at=datetime.now(UTC), revoke_reason=reason)
        )
        await self._revoke_grants(session, workspace_id=workspace_id, credential_ids=list(active_ids), reason=reason)
        await self._audit(
            session,
            workspace_id=workspace_id,
            actor=actor,
            action="credential.revoke_reference",
            subject_id=credential_ref,
            reason=reason,
            metadata={"revoked_versions": [str(item) for item in active_ids]},
        )
        return len(active_ids)

    async def _revoke_grants(
        self, session: AsyncSession, *, workspace_id: UUID, credential_ids: list[UUID], reason: str
    ) -> None:
        if not credential_ids:
            return
        await session.execute(
            sa.update(tables.credential_grants)
            .where(
                tables.credential_grants.c.workspace_id == workspace_id,
                tables.credential_grants.c.credential_id.in_(credential_ids),
                tables.credential_grants.c.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC), revoke_reason=reason)
        )

    async def _write_envelope(
        self,
        session: AsyncSession,
        *,
        workspace_id: UUID,
        credential_ref: str,
        version: int,
        plaintext: str,
        actor: str,
        rotated_from: UUID | None,
    ) -> CredentialVersion:
        credential_id = uuid4()
        sealed = self._envelope.seal(
            workspace_id=workspace_id, credential_id=credential_id, version=version, plaintext=plaintext
        )
        registry = DbNonceRegistry(session)
        await registry.register(
            sealed.master_key_version,
            sealed.wrap_nonce,
            credential_id=credential_id,
            credential_version=version,
        )
        await registry.register(
            sealed.master_key_version,
            sealed.value_nonce,
            credential_id=credential_id,
            credential_version=version,
        )
        await session.execute(
            sa.insert(tables.credential_records).values(
                id=credential_id,
                workspace_id=workspace_id,
                credential_ref=credential_ref,
                version=version,
                kind="envelope",
                status="active",
                algorithm=sealed.algorithm,
                master_key_version=sealed.master_key_version,
                wrap_nonce=sealed.wrap_nonce,
                wrapped_data_key=sealed.wrapped_data_key,
                value_nonce=sealed.value_nonce,
                ciphertext=sealed.ciphertext,
                aad=sealed.aad,
                rotated_from=rotated_from,
            )
        )
        await self._audit(
            session,
            workspace_id=workspace_id,
            actor=actor,
            action="credential.create_envelope" if rotated_from is None else "credential.rotate",
            subject_id=str(credential_id),
            reason=None,
            metadata={"version": version, "master_key_version": sealed.master_key_version},
        )
        return CredentialVersion(
            credential_id=credential_id,
            workspace_id=workspace_id,
            credential_ref=credential_ref,
            version=version,
            kind="envelope",
            status="active",
        )

    async def revoke(
        self, session: AsyncSession, *, workspace_id: UUID, credential_id: UUID, reason: str, actor: str
    ) -> None:
        await self._set_status(
            session,
            workspace_id=workspace_id,
            credential_id=credential_id,
            status="revoked",
            reason=reason,
            actor=actor,
        )
        await self._revoke_grants(session, workspace_id=workspace_id, credential_ids=[credential_id], reason=reason)

    async def soft_delete(self, session: AsyncSession, *, workspace_id: UUID, credential_id: UUID, actor: str) -> None:
        await self._set_status(
            session,
            workspace_id=workspace_id,
            credential_id=credential_id,
            status="deleted",
            reason="deleted",
            actor=actor,
        )

    async def _set_status(
        self,
        session: AsyncSession,
        *,
        workspace_id: UUID,
        credential_id: UUID,
        status: str,
        reason: str,
        actor: str,
    ) -> None:
        result = await session.execute(
            sa.update(tables.credential_records)
            .where(
                tables.credential_records.c.id == credential_id,
                tables.credential_records.c.workspace_id == workspace_id,
            )
            .values(status=status, revoked_at=datetime.now(UTC), revoke_reason=reason)
        )
        if result.rowcount == 0:
            raise SecurityError(ErrorCode.NOT_FOUND, "Không tìm thấy credential")
        await self._audit(
            session,
            workspace_id=workspace_id,
            actor=actor,
            action=f"credential.{status}",
            subject_id=str(credential_id),
            reason=reason,
            metadata={},
        )

    async def resolve(
        self, session: AsyncSession, *, workspace_id: UUID, credential_id: UUID, version: int
    ) -> SensitiveValue:
        row = (
            await session.execute(
                sa.select(tables.credential_records).where(
                    tables.credential_records.c.id == credential_id,
                    tables.credential_records.c.workspace_id == workspace_id,
                    tables.credential_records.c.version == version,
                )
            )
        ).one_or_none()
        if row is None or row.status != "active" or row.kind != "envelope":
            raise SecurityError(ErrorCode.PERMISSION_DENIED, "Credential không khả dụng cho version yêu cầu")
        return self._envelope.open_with_record(
            workspace_id=workspace_id,
            credential_id=credential_id,
            version=version,
            master_key_version=row.master_key_version,
            wrap_nonce=bytes(row.wrap_nonce),
            wrapped_data_key=bytes(row.wrapped_data_key),
            value_nonce=bytes(row.value_nonce),
            ciphertext=bytes(row.ciphertext),
        )

    async def public_metadata(self, session: AsyncSession, *, workspace_id: UUID, credential_id: UUID) -> dict:
        row = (
            await session.execute(
                sa.select(
                    tables.credential_records.c.credential_ref,
                    tables.credential_records.c.version,
                    tables.credential_records.c.kind,
                    tables.credential_records.c.status,
                    tables.credential_records.c.algorithm,
                    tables.credential_records.c.rotated_from,
                ).where(
                    tables.credential_records.c.id == credential_id,
                    tables.credential_records.c.workspace_id == workspace_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise SecurityError(ErrorCode.NOT_FOUND, "Không tìm thấy credential")
        return {
            "credential_ref": row.credential_ref,
            "version": row.version,
            "kind": row.kind,
            "status": row.status,
            "algorithm": row.algorithm,
            "rotated_from": str(row.rotated_from) if row.rotated_from else None,
        }

    async def _audit(
        self,
        session: AsyncSession,
        *,
        workspace_id: UUID,
        actor: str,
        action: str,
        subject_id: str,
        reason: str | None,
        metadata: dict,
    ) -> None:
        await session.execute(
            sa.insert(tables.audit_events).values(
                workspace_id=workspace_id,
                actor=actor,
                action=action,
                subject_type="credential",
                subject_id=subject_id,
                reason=reason,
                event_metadata=metadata,
            )
        )
