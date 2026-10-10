from __future__ import annotations

import json

import pytest
from tests.support.p22 import terminal_run
from tests.support.platform import service_workspace

from agentqa.contracts.errors import ErrorCode
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.storage.roles import ROLE_API

pytestmark = pytest.mark.asyncio


async def test_report_formats_have_provenance_and_checksums(runtime) -> None:
    user_id, workspace_id, run_id = await terminal_run(
        runtime, verdict="failed", gate="refused", assertion_result="failed"
    )
    for format in ("json", "html", "csv", "jsonl", "junit"):
        view = await runtime.reports.create(
            workspace_id=workspace_id, principal_id=user_id, actor="tester", run_id=run_id, format=format
        )
        assert view.digest
        _, payload = await runtime.reports.download(
            workspace_id=workspace_id, principal_id=user_id, report_id=view.report_id
        )
        assert payload
        if format == "json":
            document = json.loads(payload)
            assert document["provenance"]["run_id"] == str(run_id)
            assert document["detail"]["usage"]["cost_state"] == "unknown"
            assert "raw_body" not in payload.decode("utf-8")
            assert "authorization" not in payload.decode("utf-8").lower()
        if format == "csv":
            assert payload.decode("utf-8").startswith("logical_key,")
        if format == "jsonl":
            kinds = [json.loads(line)["kind"] for line in payload.decode("utf-8").splitlines() if line]
            assert kinds[0] == "run"
            assert "assertion" in kinds
        if format == "html":
            assert "<table>" in payload.decode("utf-8")
        if format == "junit":
            text = payload.decode("utf-8")
            assert "<failure" in text
            assert 'type="gate_rejection"' in text


async def test_gate_rejection_is_error_not_pass_or_skip(runtime) -> None:
    user_id, workspace_id, run_id = await terminal_run(
        runtime, verdict="inconclusive", gate="refused", assertion_result="error"
    )
    view = await runtime.reports.create(
        workspace_id=workspace_id, principal_id=user_id, actor="tester", run_id=run_id, format="junit"
    )
    _, payload = await runtime.reports.download(
        workspace_id=workspace_id, principal_id=user_id, report_id=view.report_id
    )
    text = payload.decode("utf-8")
    assert "gate_rejection" in text
    assert "<skipped" not in text


async def test_unknown_cost_is_unknown_not_zero(runtime) -> None:
    user_id, workspace_id, run_id = await terminal_run(runtime)
    view = await runtime.reports.create(
        workspace_id=workspace_id, principal_id=user_id, actor="tester", run_id=run_id, format="json"
    )
    _, payload = await runtime.reports.download(
        workspace_id=workspace_id, principal_id=user_id, report_id=view.report_id
    )
    usage = json.loads(payload)["detail"]["usage"]
    assert usage["cost_state"] == "unknown"
    assert usage["cost_total"] is None


async def test_tampered_report_integrity_is_rejected(runtime) -> None:
    user_id, workspace_id, run_id = await terminal_run(runtime)
    view = await runtime.reports.create(
        workspace_id=workspace_id, principal_id=user_id, actor="tester", run_id=run_id, format="json"
    )
    object_key = f"{workspace_id}/{run_id}/{view.artifact_id}"
    runtime.artifacts.store.write(object_key, b'{"tampered": true}')
    with pytest.raises(IdentityError) as error:
        await runtime.reports.download(workspace_id=workspace_id, principal_id=user_id, report_id=view.report_id)
    assert error.value.code == ErrorCode.EVIDENCE_MISSING


async def test_report_is_scoped_to_workspace(runtime) -> None:
    user_id, workspace_id, run_id = await terminal_run(runtime)
    view = await runtime.reports.create(
        workspace_id=workspace_id, principal_id=user_id, actor="tester", run_id=run_id, format="json"
    )
    other_user_id, _username, other_workspace_id = await service_workspace(runtime, label="other")
    with pytest.raises(IdentityError) as error:
        await runtime.reports.download(
            workspace_id=other_workspace_id, principal_id=other_user_id, report_id=view.report_id
        )
    assert error.value.code == ErrorCode.NOT_FOUND


async def test_reports_require_terminal_run(runtime) -> None:
    from uuid import uuid4

    import sqlalchemy as sa
    from tests.support.postgres import scoped_transaction

    from agentqa.platform.storage import tables

    user_id, _username, workspace_id = await service_workspace(runtime)
    run_id = uuid4()
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        await session.execute(sa.insert(tables.runs).values(id=run_id, workspace_id=workspace_id, status="running"))
    with pytest.raises(IdentityError) as error:
        await runtime.reports.create(
            workspace_id=workspace_id, principal_id=user_id, actor="tester", run_id=run_id, format="json"
        )
    assert error.value.code == ErrorCode.INPUT_INVALID
