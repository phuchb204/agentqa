from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.platform.experiments.compiler import Slot, build_slots
from agentqa.platform.experiments.manifests import ExperimentManifest, validate_manifest
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope


class SlotRunner(Protocol):
    async def run_slot(self, slot: Slot, arm_payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RevisionView:
    revision_id: UUID
    experiment_id: UUID
    logical_key: str
    revision_no: int
    content_digest: str
    content: dict[str, Any]


class ExperimentValidationError(ValueError):
    def __init__(self, incompatibilities: list[dict[str, Any]]) -> None:
        self.incompatibilities = incompatibilities
        super().__init__("; ".join(item["detail"] for item in incompatibilities))


class ExperimentService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._factory = create_session_factory(engine)

    async def create_revision(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        actor: str,
        logical_key: str,
        content: dict[str, Any],
    ) -> RevisionView:
        manifest = ExperimentManifest.model_validate(content)
        incompatibilities = validate_manifest(manifest)
        blocking = [item.model_dump() for item in incompatibilities if item.blocking]
        if blocking:
            raise ExperimentValidationError(blocking)
        digest = manifest.digest()
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            experiment_id = (
                await session.execute(
                    sa.select(tables.experiments.c.id).where(
                        tables.experiments.c.workspace_id == workspace_id,
                        tables.experiments.c.logical_key == logical_key,
                    )
                )
            ).scalar_one_or_none()
            if experiment_id is None:
                experiment_id = (
                    await session.execute(
                        sa.insert(tables.experiments)
                        .values(workspace_id=workspace_id, logical_key=logical_key)
                        .returning(tables.experiments.c.id)
                    )
                ).scalar_one()
            revision_no = (
                await session.execute(
                    sa.select(sa.func.coalesce(sa.func.max(tables.experiment_revisions.c.revision_no), 0)).where(
                        tables.experiment_revisions.c.workspace_id == workspace_id,
                        tables.experiment_revisions.c.experiment_id == experiment_id,
                    )
                )
            ).scalar_one() + 1
            revision_id = (
                await session.execute(
                    sa.insert(tables.experiment_revisions)
                    .values(
                        workspace_id=workspace_id,
                        experiment_id=experiment_id,
                        revision_no=revision_no,
                        content=content,
                        content_digest=digest,
                        author=actor,
                    )
                    .returning(tables.experiment_revisions.c.id)
                )
            ).scalar_one()
        return RevisionView(
            revision_id=revision_id,
            experiment_id=experiment_id,
            logical_key=logical_key,
            revision_no=revision_no,
            content_digest=digest,
            content=content,
        )

    async def list_revisions(self, *, workspace_id: UUID, principal_id: UUID) -> list[RevisionView]:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            rows = (
                await session.execute(
                    sa.select(
                        tables.experiment_revisions.c.id,
                        tables.experiment_revisions.c.experiment_id,
                        tables.experiment_revisions.c.revision_no,
                        tables.experiment_revisions.c.content,
                        tables.experiment_revisions.c.content_digest,
                        tables.experiments.c.logical_key,
                    )
                    .join(
                        tables.experiments,
                        (tables.experiments.c.workspace_id == tables.experiment_revisions.c.workspace_id)
                        & (tables.experiments.c.id == tables.experiment_revisions.c.experiment_id),
                    )
                    .where(tables.experiment_revisions.c.workspace_id == workspace_id)
                    .order_by(tables.experiment_revisions.c.created_at, tables.experiment_revisions.c.id)
                )
            ).all()
        return [
            RevisionView(
                revision_id=row.id,
                experiment_id=row.experiment_id,
                logical_key=row.logical_key,
                revision_no=row.revision_no,
                content_digest=row.content_digest,
                content=dict(row.content or {}),
            )
            for row in rows
        ]

    async def execute(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        revision_id: UUID,
        slot_runner: SlotRunner,
    ) -> dict[str, Any]:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            revision = (
                await session.execute(
                    sa.select(tables.experiment_revisions).where(
                        tables.experiment_revisions.c.workspace_id == workspace_id,
                        tables.experiment_revisions.c.id == revision_id,
                    )
                )
            ).one_or_none()
            if revision is None:
                raise KeyError(f"revision {revision_id} không tồn tại trong scope")
            manifest = ExperimentManifest.model_validate(revision.content)
            slots = build_slots(manifest)
            arms = {arm.arm_id: arm.model_dump(mode="json") for arm in manifest.arms}
            existing = (
                await session.execute(
                    sa.select(
                        tables.experiment_slots.c.slot_key,
                        tables.experiment_slots.c.id,
                        tables.experiment_slots.c.attempt_no,
                    ).where(
                        tables.experiment_slots.c.workspace_id == workspace_id,
                        tables.experiment_slots.c.revision_id == revision_id,
                    )
                )
            ).all()
            attempt_no = max((row.attempt_no for row in existing), default=0) + 1
            parents = {row.slot_key: row.id for row in existing if row.attempt_no == attempt_no - 1}
            rows: list[dict[str, Any]] = []
            for slot in slots:
                rows.append(
                    {
                        "workspace_id": workspace_id,
                        "revision_id": revision_id,
                        "slot_key": slot.slot_key,
                        "arm_id": slot.arm_id,
                        "case_key": slot.case_key,
                        "variant_token": slot.variant_token,
                        "data_row": slot.data_row,
                        "repetition": slot.repetition,
                        "attempt_no": attempt_no,
                        "parent_slot_id": parents.get(slot.slot_key),
                        "status": "scheduled",
                        "payload": slot.as_payload(),
                    }
                )
            await session.execute(sa.insert(tables.experiment_slots), rows)

        summary = {"attempt_no": attempt_no, "slots": len(slots), "completed": 0, "blocked": 0, "errors": 0}
        for slot in slots:
            arm_payload = arms[slot.arm_id]
            try:
                result = await slot_runner.run_slot(slot, arm_payload)
            except Exception as error:
                result = {"status": "error", "blocked_reason": f"runner_error:{type(error).__name__}"}
            status = str(result.get("status", "completed"))
            if status not in ("completed", "blocked", "error"):
                status = "error"
            summary[status if status in ("completed", "blocked") else "errors"] = (
                summary.get(status if status in ("completed", "blocked") else "errors", 0) + 1
            )
            async with self._factory() as session, session.begin():
                await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
                await session.execute(
                    sa.update(tables.experiment_slots)
                    .where(
                        tables.experiment_slots.c.workspace_id == workspace_id,
                        tables.experiment_slots.c.revision_id == revision_id,
                        tables.experiment_slots.c.slot_key == slot.slot_key,
                        tables.experiment_slots.c.attempt_no == attempt_no,
                    )
                    .values(
                        status=status,
                        blocked_reason=result.get("blocked_reason"),
                        run_id=result.get("run_id"),
                        scoring_id=result.get("scoring_id"),
                        payload={
                            **slot.as_payload(),
                            **{key: value for key, value in result.items() if key != "status"},
                        },
                    )
                )
        return summary

    async def results(self, *, workspace_id: UUID, principal_id: UUID, revision_id: UUID) -> dict[str, Any]:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            revision = (
                await session.execute(
                    sa.select(
                        tables.experiment_revisions.c.content, tables.experiment_revisions.c.content_digest
                    ).where(
                        tables.experiment_revisions.c.workspace_id == workspace_id,
                        tables.experiment_revisions.c.id == revision_id,
                    )
                )
            ).one_or_none()
            if revision is None:
                raise KeyError(f"revision {revision_id} không tồn tại trong scope")
            rows = (
                await session.execute(
                    sa.select(tables.experiment_slots)
                    .where(
                        tables.experiment_slots.c.workspace_id == workspace_id,
                        tables.experiment_slots.c.revision_id == revision_id,
                    )
                    .order_by(
                        tables.experiment_slots.c.attempt_no,
                        tables.experiment_slots.c.arm_id,
                        tables.experiment_slots.c.case_key,
                    )
                )
            ).all()
        return {
            "revision_id": str(revision_id),
            "content_digest": revision.content_digest,
            "manifest": dict(revision.content or {}),
            "slots": [
                {
                    "slot_key": row.slot_key,
                    "arm_id": row.arm_id,
                    "case_key": row.case_key,
                    "variant_token": row.variant_token,
                    "data_row": row.data_row,
                    "repetition": row.repetition,
                    "attempt_no": row.attempt_no,
                    "status": row.status,
                    "blocked_reason": row.blocked_reason,
                    "run_id": str(row.run_id) if row.run_id else None,
                    "scoring_id": str(row.scoring_id) if row.scoring_id else None,
                    "payload": dict(row.payload or {}),
                }
                for row in rows
            ],
        }
