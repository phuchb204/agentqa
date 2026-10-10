from __future__ import annotations

import json

import pytest
from tests.support.p22 import terminal_run

pytestmark = pytest.mark.asyncio


async def test_junit_marks_healed_strict_gate_rejection(runtime) -> None:
    user_id, workspace_id, run_id = await terminal_run(
        runtime, verdict="passed", gate="refused", reasons=["healed"], assertion_result="passed"
    )
    view = await runtime.reports.create(
        workspace_id=workspace_id, principal_id=user_id, actor="tester", run_id=run_id, format="junit"
    )
    _, payload = await runtime.reports.download(
        workspace_id=workspace_id, principal_id=user_id, report_id=view.report_id
    )
    text = payload.decode("utf-8")
    assert 'type="gate_rejection"' in text
    assert "healed" in text
    assert "<skipped" not in text
    assert 'failures="0"' in text
    assert 'errors="1"' in text


async def test_junit_marks_gate_error_not_pass(runtime) -> None:
    user_id, workspace_id, run_id = await terminal_run(
        runtime, verdict="inconclusive", gate="error", reasons=["evidence_missing"], assertion_result="passed"
    )
    view = await runtime.reports.create(
        workspace_id=workspace_id, principal_id=user_id, actor="tester", run_id=run_id, format="junit"
    )
    _, payload = await runtime.reports.download(
        workspace_id=workspace_id, principal_id=user_id, report_id=view.report_id
    )
    text = payload.decode("utf-8")
    assert 'type="gate_error"' in text
    assert 'errors="1"' in text
    assert "<skipped" not in text


async def test_exports_via_http_include_provenance_and_evidence(runtime, api_client) -> None:
    from uuid import uuid4

    from tests.support.security import csrf_headers, login

    created = await runtime.users.create(username=f"export-{uuid4().hex[:6]}", password="pw-123456")
    csrf = await login(api_client, created.username, "pw-123456")
    workspace = await runtime.authorization.create_workspace(
        actor_id=created.id, slug=f"exp-{uuid4().hex[:6]}", name="exports"
    )
    _u, _w, run_id = await terminal_run(runtime, verdict="failed", gate="passed", workspace=(created.id, workspace.id))

    created_report = await api_client.post(
        f"/api/v1/workspaces/{workspace.id}/runs/{run_id}/reports",
        json={"format": "csv"},
        headers=csrf_headers(csrf),
    )
    assert created_report.status_code == 201, created_report.text
    body = created_report.json()
    assert body["digest"]
    content = await api_client.get(f"/api/v1/workspaces/{workspace.id}/reports/{body['report_id']}/content")
    assert content.status_code == 200, content.text
    csv_text = content.text
    assert csv_text.startswith("logical_key,")
    assert "evidence" in csv_text.splitlines()[0]
    assert "gate" in csv_text.splitlines()[0]

    json_report = await api_client.post(
        f"/api/v1/workspaces/{workspace.id}/runs/{run_id}/reports",
        json={"format": "json"},
        headers=csrf_headers(csrf),
    )
    assert json_report.status_code == 201
    json_content = await api_client.get(
        f"/api/v1/workspaces/{workspace.id}/reports/{json_report.json()['report_id']}/content"
    )
    document = json.loads(json_content.text)
    assert document["provenance"]["run_id"] == str(run_id)
    assert document["provenance"]["gate"] == "passed"
    assert document["provenance"]["content_digests"]

    invalid = await api_client.post(
        f"/api/v1/workspaces/{workspace.id}/runs/{run_id}/reports",
        json={"format": "pdf"},
        headers=csrf_headers(csrf),
    )
    assert invalid.status_code == 422
