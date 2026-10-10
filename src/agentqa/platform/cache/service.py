from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from agentqa.contracts.canonical import digest_content
from agentqa.platform.storage import tables

CACHE_VERSION = "decision-cache/1"


class CacheState(StrEnum):
    HIT = "hit"
    MISS = "miss"
    BYPASS = "bypass"


@dataclass(frozen=True)
class CacheKeyParts:
    workspace_id: UUID
    purpose: str
    route: str
    requested_model: str
    resolved_model: str | None
    prompt_digest: str
    question_digest: str
    input_digest: str
    profile_version: str
    settings_digest: str

    def digest(self) -> str:
        material = {
            "version": CACHE_VERSION,
            "workspace_id": str(self.workspace_id),
            "purpose": self.purpose,
            "route": self.route,
            "requested_model": self.requested_model,
            "resolved_model": self.resolved_model,
            "prompt_digest": self.prompt_digest,
            "question_digest": self.question_digest,
            "input_digest": self.input_digest,
            "profile_version": self.profile_version,
            "settings_digest": self.settings_digest,
        }
        return digest_content(material)


@dataclass(frozen=True)
class CacheOutcome:
    state: CacheState
    key_digest: str
    payload: dict[str, Any] | None = None
    reason: str | None = None


class DecisionCacheService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def lookup(
        self,
        session: AsyncSession,
        parts: CacheKeyParts,
        *,
        bypass: bool = False,
        run_id: UUID | None = None,
        reason: str | None = None,
    ) -> CacheOutcome:
        key_digest = parts.digest()
        if bypass:
            await self._record_receipt(
                session, parts, key_digest=key_digest, state=CacheState.BYPASS, run_id=run_id, reason=reason
            )
            return CacheOutcome(state=CacheState.BYPASS, key_digest=key_digest, reason=reason)
        row = (
            await session.execute(
                sa.select(tables.decision_cache_entries.c.payload).where(
                    tables.decision_cache_entries.c.workspace_id == parts.workspace_id,
                    tables.decision_cache_entries.c.key_digest == key_digest,
                )
            )
        ).one_or_none()
        if row is None:
            await self._record_receipt(
                session, parts, key_digest=key_digest, state=CacheState.MISS, run_id=run_id, reason=reason
            )
            return CacheOutcome(state=CacheState.MISS, key_digest=key_digest, reason=reason)
        await self._record_receipt(
            session, parts, key_digest=key_digest, state=CacheState.HIT, run_id=run_id, reason=reason
        )
        return CacheOutcome(state=CacheState.HIT, key_digest=key_digest, payload=dict(row.payload))

    async def store(self, session: AsyncSession, parts: CacheKeyParts, payload: dict[str, Any]) -> None:
        forbidden = {"action_outcome", "action_receipt", "captures", "secret_grant", "secret_grants"}
        present = sorted(forbidden & set(payload))
        if present:
            raise ValueError(f"cache payload chứa dữ liệu action/secret không được lưu: {present}")
        key_digest = parts.digest()
        existing = (
            await session.execute(
                sa.select(tables.decision_cache_entries.c.id).where(
                    tables.decision_cache_entries.c.workspace_id == parts.workspace_id,
                    tables.decision_cache_entries.c.key_digest == key_digest,
                )
            )
        ).one_or_none()
        if existing is not None:
            return
        await session.execute(
            sa.insert(tables.decision_cache_entries).values(
                workspace_id=parts.workspace_id,
                key_digest=key_digest,
                purpose=parts.purpose,
                route=parts.route,
                requested_model=parts.requested_model,
                resolved_model=parts.resolved_model,
                prompt_digest=parts.prompt_digest,
                question_digest=parts.question_digest,
                input_digest=parts.input_digest,
                profile_version=parts.profile_version,
                settings_digest=parts.settings_digest,
                payload=payload,
            )
        )

    async def receipts_for_run(self, session: AsyncSession, run_id: UUID) -> list[dict[str, Any]]:
        rows = (
            await session.execute(
                sa.select(tables.decision_cache_receipts)
                .where(tables.decision_cache_receipts.c.run_id == run_id)
                .order_by(tables.decision_cache_receipts.c.created_at, tables.decision_cache_receipts.c.id)
            )
        ).all()
        return [
            {"receipt_id": row.id, "key_digest": row.key_digest, "state": row.state, "reason": row.reason}
            for row in rows
        ]

    async def _record_receipt(
        self,
        session: AsyncSession,
        parts: CacheKeyParts,
        *,
        key_digest: str,
        state: CacheState,
        run_id: UUID | None,
        reason: str | None,
    ) -> None:
        await session.execute(
            sa.insert(tables.decision_cache_receipts).values(
                workspace_id=parts.workspace_id,
                key_digest=key_digest,
                state=state.value,
                purpose=parts.purpose,
                route=parts.route,
                run_id=run_id,
                reason=reason,
            )
        )


def parts_from_decision(
    *,
    workspace_id: UUID,
    route: str,
    requested_model: str,
    resolved_model: str | None,
    question_digest_material: Any,
    input_digest_material: Any,
    prompt_ref: str,
    profile_version: str,
    settings: Any,
) -> CacheKeyParts:
    return CacheKeyParts(
        workspace_id=workspace_id,
        purpose="decide",
        route=route,
        requested_model=requested_model,
        resolved_model=resolved_model,
        prompt_digest=sha256(prompt_ref.encode("utf-8")).hexdigest(),
        question_digest=digest_content(question_digest_material),
        input_digest=digest_content(input_digest_material),
        profile_version=profile_version,
        settings_digest=digest_content(settings),
    )
