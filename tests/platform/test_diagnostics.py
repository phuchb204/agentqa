from __future__ import annotations

import pytest
from tests.support.p22 import terminal_run
from tests.support.platform import service_workspace

from agentqa.contracts.errors import ErrorCode
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.storage.roles import ROLE_API

pytestmark = pytest.mark.asyncio


async def test_wrong_diagnosis_does_not_change_verdict(runtime, authoring_model) -> None:
    authoring_model.reply = {
        "explanation": "Có thể do lỗi mạng phía ứng dụng.",
        "confidence": 0.3,
    }
    user_id, workspace_id, run_id = await terminal_run(
        runtime, verdict="failed", gate="refused", assertion_result="failed"
    )
    view = await runtime.diagnostics.create(
        workspace_id=workspace_id, principal_id=user_id, actor="tester", run_id=run_id
    )
    assert view.state == "completed"
    assert view.label == "Đề xuất phân tích"
    assert "lỗi mạng" in (view.explanation or "")
    assert view.confidence is not None
    assert view.model_call_id is not None
    assert view.evidence_refs

    import sqlalchemy as sa
    from tests.support.postgres import scoped_transaction

    from agentqa.platform.storage import tables

    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        run = (await session.execute(sa.select(tables.runs).where(tables.runs.c.id == run_id))).one()
        assert run.verdict == "failed"
        assert run.gate == "refused"
        call = (
            await session.execute(sa.select(tables.model_calls).where(tables.model_calls.c.id == view.model_call_id))
        ).one()
        assert call.purpose == "diagnostic"
        assert call.run_id is None
        assert call.record_state == "settled"


async def test_diagnostic_requires_terminal_run(runtime) -> None:
    user_id, _username, workspace_id = await service_workspace(runtime)
    from uuid import uuid4

    import sqlalchemy as sa
    from tests.support.postgres import scoped_transaction

    from agentqa.platform.storage import tables

    run_id = uuid4()
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        await session.execute(sa.insert(tables.runs).values(id=run_id, workspace_id=workspace_id, status="running"))
    with pytest.raises(IdentityError) as error:
        await runtime.diagnostics.create(workspace_id=workspace_id, principal_id=user_id, actor="tester", run_id=run_id)
    assert error.value.code == ErrorCode.INPUT_INVALID


async def test_provider_failure_marks_diagnostic_failed_without_touching_verdict(runtime, authoring_model) -> None:
    authoring_model.reply = None
    user_id, workspace_id, run_id = await terminal_run(runtime, verdict="inconclusive", gate="refused")
    view = await runtime.diagnostics.create(
        workspace_id=workspace_id, principal_id=user_id, actor="tester", run_id=run_id
    )
    assert view.state == "failed"
    assert view.explanation is not None and view.explanation.startswith("provider:")

    from agentqa.platform.runs.read_models import RunReadModel

    state = await RunReadModel(runtime.engines[ROLE_API]).run_state(
        workspace_id=workspace_id, principal_id=user_id, run_id=run_id
    )
    assert state is not None
    assert state["verdict"] == "inconclusive"


async def test_diagnostics_are_listed_and_linked(runtime, authoring_model) -> None:
    authoring_model.reply = {"explanation": "Kiểm tra lại locator.", "confidence": 0.5}
    user_id, workspace_id, run_id = await terminal_run(runtime, verdict="inconclusive", gate="refused")
    await runtime.diagnostics.create(workspace_id=workspace_id, principal_id=user_id, actor="tester", run_id=run_id)
    views = await runtime.diagnostics.list_for_run(workspace_id=workspace_id, principal_id=user_id, run_id=run_id)
    assert views is not None and len(views) == 1
    assert views[0].run_id == run_id


async def test_comparison_denominators_and_provenance_authoritative(runtime, authoring_model) -> None:
    authoring_model.reply = {"explanation": "Sai hướng.", "confidence": 0.1}
    user_id, workspace_id, run_a = await terminal_run(runtime, verdict="passed", gate="passed")
    _user_b, _ws_b, run_b = await terminal_run(
        runtime,
        verdict="failed",
        gate="refused",
        assertion_result="failed",
        workspace=(user_id, workspace_id),
    )
    before = await runtime.comparison.compare(workspace_id=workspace_id, principal_id=user_id, run_a=run_a, run_b=run_b)
    assert before is not None
    assert before["provenance"]["a"]["gate_profile"] == "strict"
    assert before["denominators"]["a"]["executions_total"] == 1
    assert before["denominators"]["b"]["executions_terminal"] == 1
    await runtime.diagnostics.create(workspace_id=workspace_id, principal_id=user_id, actor="tester", run_id=run_b)
    after = await runtime.comparison.compare(workspace_id=workspace_id, principal_id=user_id, run_a=run_a, run_b=run_b)
    assert after is not None
    assert after["denominators"] == before["denominators"]
    assert after["provenance"] == before["provenance"]
    assert after["metrics"] == before["metrics"]
