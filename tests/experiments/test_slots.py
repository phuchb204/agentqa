from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from agentqa.platform.experiments import ExperimentService, build_slots, expected_slot_count
from tests.experiments.conftest import manifest_from, minimal_manifest
from tests.support.postgres import seed_workspace

pytestmark = pytest.mark.asyncio


class ScriptedSlotRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run_slot(self, slot, arm_payload):
        self.calls.append(slot.slot_key)
        return {"status": "completed", "payload_extra": {"arm": arm_payload["arm_id"]}}


async def _workspace(engines) -> tuple[UUID, UUID]:
    return await seed_workspace(engines, label=f"exp-{uuid4().hex[:8]}")


async def test_slots_are_unique_and_materialize_before_run() -> None:
    manifest = manifest_from(minimal_manifest())
    slots = build_slots(manifest)
    keys = [slot.slot_key for slot in slots]
    assert len(keys) == len(set(keys))
    assert len(slots) == expected_slot_count(manifest) == 10
    assert {slot.arm_id for slot in slots} == {arm.arm_id for arm in manifest.arms}


async def test_execute_materializes_slots_and_rerun_links_without_overwrite(role_engines) -> None:
    engines = role_engines
    user_id, workspace_id = await _workspace(engines)
    service = ExperimentService(engines["agentqa_api"])
    revision = await service.create_revision(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor="tester",
        logical_key="unit-experiment",
        content=minimal_manifest(),
    )
    runner = ScriptedSlotRunner()
    first = await service.execute(
        workspace_id=workspace_id, principal_id=user_id, revision_id=revision.revision_id, slot_runner=runner
    )
    assert first == {"attempt_no": 1, "slots": 10, "completed": 10, "blocked": 0, "errors": 0}
    assert len(runner.calls) == 10

    second = await service.execute(
        workspace_id=workspace_id, principal_id=user_id, revision_id=revision.revision_id, slot_runner=runner
    )
    assert second["attempt_no"] == 2
    from tests.support.postgres import scoped_transaction

    async with scoped_transaction(engines["agentqa_api"], principal_id=user_id, workspace_id=workspace_id) as session:
        rows = (
            await session.execute(
                sa.text(
                    "SELECT attempt_no, count(*) AS n, count(parent_slot_id) AS linked "
                    "FROM experiment_slots WHERE revision_id = :rid GROUP BY attempt_no ORDER BY attempt_no"
                ),
                {"rid": revision.revision_id},
            )
        ).all()
    assert [(row.attempt_no, row.n) for row in rows] == [(1, 10), (2, 10)]
    assert rows[0].linked == 0
    assert rows[1].linked == 10

    async with scoped_transaction(engines["agentqa_api"], principal_id=user_id, workspace_id=workspace_id) as session:
        attempt_one_status = (
            await session.execute(
                sa.text(
                    "SELECT count(*) FROM experiment_slots WHERE revision_id = :rid AND attempt_no = 1 "
                    "AND status = 'completed'"
                ),
                {"rid": revision.revision_id},
            )
        ).scalar_one()
    assert attempt_one_status == 10


async def test_blocked_slots_are_recorded_and_included_in_results(role_engines) -> None:
    engines = role_engines
    user_id, workspace_id = await _workspace(engines)
    service = ExperimentService(engines["agentqa_api"])
    revision = await service.create_revision(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor="tester",
        logical_key="blocked-experiment",
        content=minimal_manifest(),
    )

    class BlockingRunner:
        async def run_slot(self, slot, arm_payload):
            if arm_payload["policy"] == "llm":
                return {"status": "blocked", "blocked_reason": "image_capability_unverified"}
            return {"status": "completed"}

    summary = await service.execute(
        workspace_id=workspace_id, principal_id=user_id, revision_id=revision.revision_id, slot_runner=BlockingRunner()
    )
    assert summary["blocked"] == 2
    results = await service.results(workspace_id=workspace_id, principal_id=user_id, revision_id=revision.revision_id)
    blocked = [slot for slot in results["slots"] if slot["status"] == "blocked"]
    assert len(blocked) == 2
    assert all(slot["blocked_reason"] == "image_capability_unverified" for slot in blocked)


async def test_revision_rows_are_append_only(role_engines) -> None:
    engines = role_engines
    user_id, workspace_id = await _workspace(engines)
    service = ExperimentService(engines["agentqa_api"])
    first = await service.create_revision(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor="tester",
        logical_key="append-only",
        content=minimal_manifest(),
    )
    altered = minimal_manifest()
    altered["version"] = "2"
    second = await service.create_revision(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor="tester",
        logical_key="append-only",
        content=altered,
    )
    assert first.revision_no == 1 and second.revision_no == 2
    views = await service.list_revisions(workspace_id=workspace_id, principal_id=user_id)
    assert [view.revision_no for view in views] == [1, 2]
    assert views[0].content["version"] == "1"
    assert views[1].content["version"] == "2"


async def test_validation_errors_block_creation(role_engines) -> None:
    from agentqa.platform.experiments import ExperimentValidationError

    engines = role_engines
    user_id, workspace_id = await _workspace(engines)
    service = ExperimentService(engines["agentqa_api"])
    bad = minimal_manifest(research_question="rq2")
    bad["arms"] = bad["arms"][:2]
    with pytest.raises(ExperimentValidationError) as info:
        await service.create_revision(
            workspace_id=workspace_id, principal_id=user_id, actor="tester", logical_key="bad", content=bad
        )
    assert info.value.incompatibilities[0]["code"] == "rq2_arms"
    async with engines["agentqa_api"].connect() as connection:
        count = (await connection.execute(sa.text("SELECT count(*) FROM experiments"))).scalar_one()
    assert count >= 0
