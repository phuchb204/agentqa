from __future__ import annotations

import json

import pytest
import sqlalchemy as sa
from tests.support.p22 import terminal_run
from tests.support.postgres import scoped_transaction

from agentqa.contracts.errors import ErrorCode
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API

pytestmark = pytest.mark.asyncio


async def test_issue_package_preview_and_download_without_send(runtime) -> None:
    user_id, workspace_id, run_id = await terminal_run(
        runtime, verdict="failed", gate="refused", assertion_result="failed", with_artifacts=True
    )
    view = await runtime.reports.create_issue_package(
        workspace_id=workspace_id, principal_id=user_id, actor="tester", run_id=run_id
    )
    assert view.digest
    preview = view.preview
    assert preview["schema_version"] == "issue-package/1"
    assert preview["summary"]["verdict"] == "failed"
    assert preview["summary"]["first_problem"]["assertion_id"] == "item_exists_once"
    assert preview["configuration"]["gate_profile"] == "strict"
    assert preview["steps"]
    assert preview["missing_evidence"] and preview["missing_evidence"][0]["reason"] == "expired"

    artifact_id, payload = await runtime.reports.download_issue_package(
        workspace_id=workspace_id, principal_id=user_id, package_id=view.package_id
    )
    assert artifact_id == view.artifact_id
    assert json.loads(payload)["summary"]["verdict"] == "failed"

    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        outbox = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(tables.outbox_deliveries)
                .where(tables.outbox_deliveries.c.workspace_id == workspace_id)
            )
        ).scalar_one()
        assert outbox == 0


async def test_issue_package_integrity_and_scope(runtime) -> None:
    user_id, workspace_id, run_id = await terminal_run(runtime, verdict="inconclusive", gate="refused")
    view = await runtime.reports.create_issue_package(
        workspace_id=workspace_id, principal_id=user_id, actor="tester", run_id=run_id
    )
    object_key = f"{workspace_id}/{run_id}/{view.artifact_id}"
    runtime.artifacts.store.write(object_key, b"{}")
    with pytest.raises(IdentityError) as error:
        await runtime.reports.download_issue_package(
            workspace_id=workspace_id, principal_id=user_id, package_id=view.package_id
        )
    assert error.value.code == ErrorCode.EVIDENCE_MISSING
