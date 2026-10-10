from __future__ import annotations

import copy
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from tests.support.authoring import ScriptedAuthoringGo, authored_case, proposal_payload
from tests.support.documents import make_text_pdf
from tests.support.postgres import scoped_transaction
from tests.support.security import csrf_headers

from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API

pytestmark = pytest.mark.asyncio


async def _create_entity(api_client, csrf: str, workspace_id: str, kind: str, logical_key: str) -> str:
    response = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/{kind}s",
        json={"logical_key": logical_key},
        headers=csrf_headers(csrf),
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _create_source_with_document(api_client, csrf: str, workspace_id: str) -> tuple[str, int]:
    source_id = await _create_entity(api_client, csrf, workspace_id, "source", "flow_source")
    upload = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/sources/{source_id}/revisions",
        data={"logical_key": "flow_source"},
        files={"file": ("flow.pdf", make_text_pdf(["Checkout flow page"]), "application/pdf")},
        headers=csrf_headers(csrf),
    )
    assert upload.status_code == 200, upload.text
    return source_id, upload.json()["revision"]["revision_no"]


async def _authoring_job(api_client, csrf: str, workspace_id: str, *, sources: list[dict] | None = None):
    return await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/authoring-jobs",
        json={
            "goal": "Xác nhận luồng checkout hoàn tất",
            "url": "http://127.0.0.1:8000/checkout",
            "expectations": ["Sau khi xác nhận, đường dẫn kết thúc bằng /done"],
            "requirement_keys": ["flow_requirement"],
            "sources": sources or [],
        },
        headers=csrf_headers(csrf),
    )


async def _create_case(api_client, csrf: str, workspace_id: str, logical_key: str = "authored_case") -> str:
    response = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases",
        json={"logical_key": logical_key},
        headers=csrf_headers(csrf),
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _model_calls(runtime, workspace_id: str) -> list:
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=uuid4(), workspace_id=UUID(workspace_id)
    ) as session:
        return (
            await session.execute(
                sa.select(tables.model_calls).where(
                    tables.model_calls.c.workspace_id == UUID(workspace_id),
                    tables.model_calls.c.purpose == "authoring",
                )
            )
        ).all()


async def _job_row(runtime, workspace_id: str, job_id: str):
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=uuid4(), workspace_id=UUID(workspace_id)
    ) as session:
        return (
            await session.execute(sa.select(tables.authoring_jobs).where(tables.authoring_jobs.c.id == UUID(job_id)))
        ).one()


async def test_authoring_job_produces_typed_proposals_and_call_ledger(
    api_client, runtime, owner, authoring_model: ScriptedAuthoringGo
) -> None:
    workspace_id, csrf = owner
    await _create_entity(api_client, csrf, workspace_id, "requirement", "flow_requirement")
    source_id, revision_no = await _create_source_with_document(api_client, csrf, workspace_id)
    authoring_model.reply = {
        "proposals": [
            proposal_payload(case=authored_case("positive_case"), kind="positive")["proposals"][0],
            proposal_payload(case=authored_case("negative_case", expected="/error"), kind="negative")["proposals"][0],
            proposal_payload(
                case=authored_case("boundary_case", inferred=True),
                kind="boundary",
                provenance=[{"path": "source_defs.flow_source", "source": "inferred", "ref": "observed-page"}],
            )["proposals"][0],
        ]
    }

    response = await _authoring_job(
        api_client, csrf, workspace_id, sources=[{"source_id": source_id, "revision_no": revision_no}]
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "succeeded"
    assert body["kind"] == "authoring"
    assert len(body["proposals"]) == 3
    kinds = {proposal["case_kind"] for proposal in body["proposals"]}
    assert kinds == {"positive", "negative", "boundary"}
    for proposal in body["proposals"]:
        assert proposal["status"] == "proposed"
        assert proposal["requirement_keys"] == ["flow_requirement"]
        assert proposal["content"]["schema_version"] == "case/1"
        assert proposal["provenance"]
    inferred = next(item for item in body["proposals"] if item["case_kind"] == "boundary")
    assert any(entry["source"] == "inferred" for entry in inferred["provenance"])

    calls = await _model_calls(runtime, workspace_id)
    assert len(calls) == 1
    assert calls[0].record_state == "settled"
    assert calls[0].usage_input == 120
    assert calls[0].usage_output == 80
    assert calls[0].run_id is None

    job_row = await _job_row(runtime, workspace_id, body["job_id"])
    pinned = job_row.input
    assert pinned["input_digest"]
    assert pinned["sources"][0]["file_digest"]
    assert pinned["sources"][0]["revision_no"] == revision_no
    request = authoring_model.requests[0]
    assert "Checkout flow page" in request.messages[1].parts[0].text


async def test_invalid_proposal_is_rejected_fail_closed(
    api_client, owner, authoring_model: ScriptedAuthoringGo
) -> None:
    workspace_id, csrf = owner
    await _create_entity(api_client, csrf, workspace_id, "requirement", "flow_requirement")
    malicious = authored_case("malicious_case")
    malicious["nodes"].append({"id": "shell", "kind": "shell", "command": "rm -rf /"})
    authoring_model.reply = {
        "proposals": [
            proposal_payload(case=authored_case("valid_case"))["proposals"][0],
            proposal_payload(case=malicious, title="Malicious")["proposals"][0],
        ]
    }
    response = await _authoring_job(api_client, csrf, workspace_id)
    assert response.status_code == 200, response.text
    proposals = response.json()["proposals"]
    by_title = {proposal["title"]: proposal for proposal in proposals}
    assert by_title["Malicious"]["status"] == "rejected"
    assert by_title["Malicious"]["rejection_reason"] == "case_invalid"
    valid = next(proposal for proposal in proposals if proposal["status"] == "proposed")

    case_id = await _create_case(api_client, csrf, workspace_id)
    applied = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/proposals/{by_title['Malicious']['proposal_id']}/apply",
        json={"case_id": case_id, "expected_edit_version": 0},
        headers={**csrf_headers(csrf), "If-Match": '"0"'},
    )
    assert applied.status_code == 422
    applied_valid = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/proposals/{valid['proposal_id']}/apply",
        json={"case_id": case_id, "expected_edit_version": 0},
        headers={**csrf_headers(csrf), "If-Match": '"0"'},
    )
    assert applied_valid.status_code == 200, applied_valid.text


async def test_apply_proposal_diff_and_stale_edit_conflict(
    api_client, owner, authoring_model: ScriptedAuthoringGo
) -> None:
    workspace_id, csrf = owner
    await _create_entity(api_client, csrf, workspace_id, "requirement", "flow_requirement")
    authoring_model.reply = proposal_payload(case=authored_case("diff_case"))
    job = (await _authoring_job(api_client, csrf, workspace_id)).json()
    proposal_id = job["proposals"][0]["proposal_id"]
    case_id = await _create_case(api_client, csrf, workspace_id, "diff_case")

    applied = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/proposals/{proposal_id}/apply",
        json={"case_id": case_id, "expected_edit_version": 0},
        headers={**csrf_headers(csrf), "If-Match": '"0"'},
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["edit_version"] == 1
    ops = {(entry["op"], entry.get("node_id") or entry.get("name")) for entry in body["diff"]}
    assert ("add_node", "open") in ops
    assert ("add_node", "check") in ops
    assert ("add_source", "flow_source") in ops

    stale = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/proposals/{proposal_id}/apply",
        json={"case_id": case_id, "expected_edit_version": 0},
        headers={**csrf_headers(csrf), "If-Match": '"0"'},
    )
    assert stale.status_code == 412

    missing = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/proposals/{proposal_id}/apply",
        json={"case_id": case_id, "expected_edit_version": 1},
        headers=csrf_headers(csrf),
    )
    assert missing.status_code == 428


async def test_promote_requires_source_confirmation_and_complete_assertions(
    api_client, owner, authoring_model: ScriptedAuthoringGo
) -> None:
    workspace_id, csrf = owner
    await _create_entity(api_client, csrf, workspace_id, "requirement", "flow_requirement")
    authoring_model.reply = proposal_payload(
        case=authored_case("inferred_case", inferred=True),
        provenance=[{"path": "source_defs.flow_source", "source": "inferred", "ref": "observed-page"}],
    )
    job = (await _authoring_job(api_client, csrf, workspace_id)).json()
    proposal_id = job["proposals"][0]["proposal_id"]
    case_id = await _create_case(api_client, csrf, workspace_id, "inferred_case")
    applied = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/proposals/{proposal_id}/apply",
        json={"case_id": case_id, "expected_edit_version": 0},
        headers={**csrf_headers(csrf), "If-Match": '"0"'},
    )
    assert applied.status_code == 200, applied.text

    blocked = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/promote",
        headers={**csrf_headers(csrf), "If-Match": '"1"'},
    )
    assert blocked.status_code == 422
    assert "source" in blocked.text.lower()

    confirmed = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/confirm-sources",
        json={"source_names": ["flow_source"]},
        headers={**csrf_headers(csrf), "If-Match": '"1"'},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["edit_version"] == 2
    assert confirmed.json()["content"]["source_defs"]["flow_source"]["confirmation_ref"]

    promoted = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/promote",
        headers={**csrf_headers(csrf), "If-Match": '"2"'},
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["revision_no"] == 1

    missing_source = copy.deepcopy(authored_case("missing_source_case"))
    missing_source["nodes"][1]["assertions"][0]["source_refs"] = []
    missing_source["completion"]["required_assertions"] = []
    draft = await api_client.patch(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft",
        json={"content": missing_source},
        headers={**csrf_headers(csrf), "If-Match": '"2"'},
    )
    assert draft.status_code == 200
    refused = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/promote",
        headers={**csrf_headers(csrf), "If-Match": '"3"'},
    )
    assert refused.status_code == 422


async def test_draft_run_is_provisional_and_never_creates_ready(
    api_client, runtime, owner, authoring_model: ScriptedAuthoringGo
) -> None:
    workspace_id, csrf = owner
    await _create_entity(api_client, csrf, workspace_id, "requirement", "flow_requirement")
    authoring_model.reply = proposal_payload(case=authored_case("draft_run_case"))
    job = (await _authoring_job(api_client, csrf, workspace_id)).json()
    proposal_id = job["proposals"][0]["proposal_id"]
    case_id = await _create_case(api_client, csrf, workspace_id, "draft_run_case")
    await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/proposals/{proposal_id}/apply",
        json={"case_id": case_id, "expected_edit_version": 0},
        headers={**csrf_headers(csrf), "If-Match": '"0"'},
    )

    idempotency_key = uuid4().hex
    first = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/run",
        json={"idempotency_key": idempotency_key},
        headers=csrf_headers(csrf),
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["provisional"] is True
    assert body["planned_executions"] == 1
    assert body["blocked"] is False

    again = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/run",
        json={"idempotency_key": idempotency_key},
        headers=csrf_headers(csrf),
    )
    assert again.status_code == 200
    assert again.json()["run_id"] == body["run_id"]

    revisions = await api_client.get(f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/revisions")
    assert revisions.status_code == 200
    assert revisions.json() == []

    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=uuid4(), workspace_id=UUID(workspace_id)
    ) as session:
        snapshot = (
            await session.execute(
                sa.select(tables.run_snapshots).where(tables.run_snapshots.c.run_id == UUID(body["run_id"]))
            )
        ).one()
        execution = (
            await session.execute(
                sa.select(tables.executions).where(tables.executions.c.run_id == UUID(body["run_id"]))
            )
        ).one()
    assert snapshot.content["provisional"] is True
    assert snapshot.content["draft_case"]["logical_key"] == "draft_run_case"
    assert execution.case_revision_id is None


async def test_authoring_fails_closed_on_bad_model_output(
    api_client, runtime, owner, authoring_model: ScriptedAuthoringGo
) -> None:
    workspace_id, csrf = owner
    await _create_entity(api_client, csrf, workspace_id, "requirement", "flow_requirement")
    authoring_model.reply = {"not_proposals": []}
    response = await _authoring_job(api_client, csrf, workspace_id)
    assert response.status_code == 400
    jobs = await _latest_job(runtime, workspace_id)
    assert jobs.state == "failed"
    assert jobs.error_reason == "invalid_model_result"

    authoring_model.reply = None
    failed = await _authoring_job(api_client, csrf, workspace_id)
    assert failed.status_code == 400
    jobs = await _latest_job(runtime, workspace_id)
    assert jobs.state == "failed"
    assert jobs.error_reason == "model_call_failed"
    calls = await _model_calls(runtime, workspace_id)
    assert any(call.record_state == "settled" and call.outcome == "failed" for call in calls)


async def _latest_job(runtime, workspace_id: str):
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=uuid4(), workspace_id=UUID(workspace_id)
    ) as session:
        return (
            await session.execute(
                sa.select(tables.authoring_jobs)
                .where(tables.authoring_jobs.c.workspace_id == UUID(workspace_id))
                .order_by(tables.authoring_jobs.c.created_at.desc(), tables.authoring_jobs.c.id.desc())
                .limit(1)
            )
        ).one()
