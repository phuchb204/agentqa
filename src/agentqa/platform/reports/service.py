from __future__ import annotations

import csv
import html
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4
from xml.sax.saxutils import quoteattr

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.artifacts import ArtifactKind
from agentqa.contracts.canonical import digest_artifact_bytes
from agentqa.contracts.errors import ErrorCode
from agentqa.platform.artifacts.service import ArtifactService
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.runs.read_models import RunReadModel
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope

FORMATS = ("json", "html", "csv", "jsonl", "junit")
MEDIA_TYPES = {
    "json": "application/json",
    "html": "text/html",
    "csv": "text/csv",
    "jsonl": "application/x-ndjson",
    "junit": "application/xml",
}
ISSUE_PACKAGE_VERSION = "issue-package/1"


@dataclass(frozen=True)
class ReportView:
    report_id: UUID
    run_id: UUID
    format: str
    artifact_id: UUID
    digest: str | None
    media_type: str
    created_at: datetime


@dataclass(frozen=True)
class IssuePackageView:
    package_id: UUID
    run_id: UUID
    artifact_id: UUID
    digest: str | None
    preview: dict[str, Any]
    created_at: datetime


def _report_view(row) -> ReportView:
    return ReportView(
        report_id=row.id,
        run_id=row.run_id,
        format=row.format,
        artifact_id=row.artifact_id,
        digest=row.digest,
        media_type=row.media_type,
        created_at=row.created_at,
    )


class ReportService:
    def __init__(self, engine: AsyncEngine, artifacts: ArtifactService) -> None:
        self._engine = engine
        self._factory = create_session_factory(engine)
        self._artifacts = artifacts

    async def create(
        self, *, workspace_id: UUID, principal_id: UUID, actor: str, run_id: UUID, format: str
    ) -> ReportView:
        if format not in FORMATS:
            raise IdentityError(ErrorCode.INPUT_INVALID, f"Định dạng report không hỗ trợ: {format}")
        detail = await self._run_detail(workspace_id=workspace_id, principal_id=principal_id, run_id=run_id)
        payload, media_type = render_report(detail, format)
        artifact = await self._artifacts.stage(
            workspace_id=workspace_id,
            principal_id=principal_id,
            kind=ArtifactKind.REPORT.value,
            media_type=media_type,
            payload=payload,
            run_id=run_id,
        )
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            row = (
                await session.execute(
                    sa.insert(tables.reports)
                    .values(
                        id=uuid4(),
                        workspace_id=workspace_id,
                        run_id=run_id,
                        format=format,
                        artifact_id=artifact.id,
                        digest=artifact.digest,
                        media_type=media_type,
                        created_by=actor,
                    )
                    .returning(tables.reports)
                )
            ).one()
        return _report_view(row)

    async def list_for_run(self, *, workspace_id: UUID, principal_id: UUID, run_id: UUID) -> list[ReportView] | None:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            run = (
                await session.execute(
                    sa.select(tables.runs.c.id).where(
                        tables.runs.c.workspace_id == workspace_id, tables.runs.c.id == run_id
                    )
                )
            ).one_or_none()
            if run is None:
                return None
            rows = (
                await session.execute(
                    sa.select(tables.reports)
                    .where(tables.reports.c.workspace_id == workspace_id, tables.reports.c.run_id == run_id)
                    .order_by(tables.reports.c.created_at, tables.reports.c.id)
                )
            ).all()
        return [_report_view(row) for row in rows]

    async def download(self, *, workspace_id: UUID, principal_id: UUID, report_id: UUID) -> tuple[ReportView, bytes]:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            row = (
                await session.execute(
                    sa.select(tables.reports).where(
                        tables.reports.c.workspace_id == workspace_id, tables.reports.c.id == report_id
                    )
                )
            ).one_or_none()
        if row is None:
            raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy report")
        payload = await self._artifacts.open_bytes(
            workspace_id=workspace_id, principal_id=principal_id, artifact_id=row.artifact_id
        )
        if row.digest and digest_artifact_bytes(payload) != row.digest:
            raise IdentityError(ErrorCode.EVIDENCE_MISSING, "Report integrity không khớp")
        return _report_view(row), payload

    async def create_issue_package(
        self, *, workspace_id: UUID, principal_id: UUID, actor: str, run_id: UUID
    ) -> IssuePackageView:
        detail = await self._run_detail(workspace_id=workspace_id, principal_id=principal_id, run_id=run_id)
        preview = build_issue_package(detail)
        payload = json.dumps(preview, ensure_ascii=False, sort_keys=True, indent=2, default=str).encode("utf-8")
        artifact = await self._artifacts.stage(
            workspace_id=workspace_id,
            principal_id=principal_id,
            kind=ArtifactKind.EXPORT.value,
            media_type="application/json",
            payload=payload,
            run_id=run_id,
        )
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            row = (
                await session.execute(
                    sa.insert(tables.issue_packages)
                    .values(
                        id=uuid4(),
                        workspace_id=workspace_id,
                        run_id=run_id,
                        artifact_id=artifact.id,
                        digest=artifact.digest,
                        created_by=actor,
                    )
                    .returning(tables.issue_packages)
                )
            ).one()
        return IssuePackageView(
            package_id=row.id,
            run_id=row.run_id,
            artifact_id=row.artifact_id,
            digest=row.digest,
            preview=preview,
            created_at=row.created_at,
        )

    async def download_issue_package(
        self, *, workspace_id: UUID, principal_id: UUID, package_id: UUID
    ) -> tuple[UUID, bytes]:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            row = (
                await session.execute(
                    sa.select(tables.issue_packages).where(
                        tables.issue_packages.c.workspace_id == workspace_id,
                        tables.issue_packages.c.id == package_id,
                    )
                )
            ).one_or_none()
        if row is None:
            raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy issue package")
        payload = await self._artifacts.open_bytes(
            workspace_id=workspace_id, principal_id=principal_id, artifact_id=row.artifact_id
        )
        if row.digest and digest_artifact_bytes(payload) != row.digest:
            raise IdentityError(ErrorCode.EVIDENCE_MISSING, "Issue package integrity không khớp")
        return row.artifact_id, payload

    async def _run_detail(self, *, workspace_id: UUID, principal_id: UUID, run_id: UUID) -> dict[str, Any]:
        detail = await RunReadModel(self._engine).run_detail(
            workspace_id=workspace_id, principal_id=principal_id, run_id=run_id
        )
        if detail is None:
            raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy run")
        if not detail["terminal"]:
            raise IdentityError(ErrorCode.INPUT_INVALID, "Report chỉ tạo sau khi run terminal")
        return detail


def render_report(detail: dict[str, Any], format: str) -> tuple[bytes, str]:
    if format == "json":
        payload = json.dumps(_json_document(detail), ensure_ascii=False, sort_keys=True, indent=2, default=str).encode(
            "utf-8"
        )
    elif format == "csv":
        payload = _csv_document(detail)
    elif format == "jsonl":
        payload = _jsonl_document(detail)
    elif format == "html":
        payload = _html_document(detail)
    elif format == "junit":
        payload = _junit_document(detail)
    else:  # pragma: no cover - guarded by caller
        raise ValueError(format)
    return payload, MEDIA_TYPES[format]


def _provenance(detail: dict[str, Any]) -> dict[str, Any]:
    snapshot = detail.get("snapshot", {})
    return {
        "run_id": str(detail.get("run_id")),
        "status": detail.get("status"),
        "verdict": detail.get("verdict"),
        "gate": detail.get("gate"),
        "policy": snapshot.get("policy"),
        "observation_mode": snapshot.get("observation_mode"),
        "gate_profile": snapshot.get("gate_profile"),
        "calibration_ref": snapshot.get("calibration_ref"),
        "content_digests": snapshot.get("content_digests", []),
        "usage": detail.get("usage", {}),
    }


def _json_document(detail: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "run-report/1", "provenance": _provenance(detail), "detail": detail}


def _csv_document(detail: dict[str, Any]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "logical_key",
            "execution_status",
            "execution_verdict",
            "checkpoint_id",
            "assertion_id",
            "result",
            "expected",
            "observed",
            "evidence",
            "gate",
        ]
    )
    for execution in detail.get("executions", []):
        for assertion in execution.get("assertions", []):
            proof = assertion.get("proof", {})
            writer.writerow(
                [
                    execution.get("logical_key"),
                    execution.get("status"),
                    execution.get("verdict"),
                    assertion.get("checkpoint_id"),
                    assertion.get("assertion_id"),
                    assertion.get("result"),
                    proof.get("expected"),
                    proof.get("observed"),
                    proof.get("evidence"),
                    detail.get("gate"),
                ]
            )
    return buffer.getvalue().encode("utf-8")


def _jsonl_document(detail: dict[str, Any]) -> bytes:
    lines = [
        json.dumps({"kind": "run", "provenance": _provenance(detail)}, ensure_ascii=False, sort_keys=True, default=str)
    ]
    for execution in detail.get("executions", []):
        lines.append(
            json.dumps(
                {
                    "kind": "execution",
                    "execution_id": str(execution.get("execution_id")),
                    "logical_key": execution.get("logical_key"),
                    "status": execution.get("status"),
                    "verdict": execution.get("verdict"),
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        )
        for assertion in execution.get("assertions", []):
            lines.append(
                json.dumps(
                    {
                        "kind": "assertion",
                        "logical_key": execution.get("logical_key"),
                        "checkpoint_id": assertion.get("checkpoint_id"),
                        "assertion_id": assertion.get("assertion_id"),
                        "result": assertion.get("result"),
                        "proof": assertion.get("proof", {}),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
            )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _html_document(detail: dict[str, Any]) -> bytes:
    provenance = _provenance(detail)
    rows = []
    for execution in detail.get("executions", []):
        for assertion in execution.get("assertions", []):
            proof = assertion.get("proof", {})
            rows.append(
                "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                    html.escape(str(execution.get("logical_key"))),
                    html.escape(str(assertion.get("checkpoint_id"))),
                    html.escape(str(assertion.get("assertion_id"))),
                    html.escape(str(assertion.get("result"))),
                    html.escape(str(proof.get("expected"))),
                    html.escape(str(proof.get("observed"))),
                    html.escape(str(proof.get("evidence"))),
                )
            )
    document = (
        "<!doctype html><html lang='vi'><head><meta charset='utf-8'><title>Báo cáo lượt chạy</title></head><body>"
        f"<h1>Báo cáo lượt chạy {html.escape(str(provenance['run_id']))}</h1>"
        f"<p>Verdict: {html.escape(str(provenance['verdict']))} · Gate: {html.escape(str(provenance['gate']))}</p>"
        "<table><thead><tr><th>Ca</th><th>Checkpoint</th><th>Assertion</th><th>Kết quả</th>"
        "<th>Expected</th><th>Observed</th><th>Evidence</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></body></html>"
    )
    return document.encode("utf-8")


def _junit_document(detail: dict[str, Any]) -> bytes:
    executions = detail.get("executions", [])
    gate_marker = detail.get("gate") in ("refused", "error")
    total = sum(len(execution.get("assertions", [])) for execution in executions) + (1 if gate_marker else 0)
    failures = sum(
        1
        for execution in executions
        for assertion in execution.get("assertions", [])
        if assertion.get("result") == "failed"
    )
    errors = sum(
        1
        for execution in executions
        for assertion in execution.get("assertions", [])
        if assertion.get("result") == "error"
    ) + (1 if gate_marker else 0)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<testsuites name="agentqa" tests="{total}" failures="{failures}" errors="{errors}">',
    ]
    for execution in executions:
        parts.append(
            f"<testsuite name={quoteattr(str(execution.get('logical_key')))} "
            f"status={quoteattr(str(execution.get('status')))} verdict={quoteattr(str(execution.get('verdict')))}>"
        )
        for assertion in execution.get("assertions", []):
            name = f"{execution.get('logical_key')}.{assertion.get('checkpoint_id')}.{assertion.get('assertion_id')}"
            proof = assertion.get("proof", {})
            message = (
                f"expected={proof.get('expected')} observed={proof.get('observed')} "
                f"evidence={proof.get('evidence')} reason={proof.get('reason')}"
            )
            result = assertion.get("result")
            if result == "failed":
                parts.append(f"<testcase name={quoteattr(name)}><failure message={quoteattr(message)}/></testcase>")
            elif result == "error":
                parts.append(f"<testcase name={quoteattr(name)}><error message={quoteattr(message)}/></testcase>")
            else:
                parts.append(f"<testcase name={quoteattr(name)}/>")
        parts.append("</testsuite>")
    gate = detail.get("gate")
    if gate in ("refused", "error"):
        reasons = "; ".join(str(reason) for reason in detail.get("reasons", []))
        gate_type = "gate_rejection" if gate == "refused" else "gate_error"
        parts.append(
            '<testsuite name="gate">'
            f"<testcase name={quoteattr(gate_type)}><error type={quoteattr(gate_type)} message={quoteattr(reasons)}/>"
            "</testcase></testsuite>"
        )
    parts.append("</testsuites>")
    return ("\n".join(parts) + "\n").encode("utf-8")


def build_issue_package(detail: dict[str, Any]) -> dict[str, Any]:
    executions = detail.get("executions", [])
    first_problem = None
    steps: list[dict[str, Any]] = []
    for execution in executions:
        for assertion in execution.get("assertions", []):
            proof = assertion.get("proof", {})
            entry = {
                "logical_key": execution.get("logical_key"),
                "checkpoint_id": assertion.get("checkpoint_id"),
                "assertion_id": assertion.get("assertion_id"),
                "result": assertion.get("result"),
                "expected": proof.get("expected"),
                "observed": proof.get("observed"),
                "evidence": proof.get("evidence"),
                "reason": proof.get("reason"),
            }
            steps.append(entry)
            if first_problem is None and assertion.get("result") in ("failed", "error"):
                first_problem = entry
    return {
        "schema_version": ISSUE_PACKAGE_VERSION,
        "summary": {
            "run_id": str(detail.get("run_id")),
            "status": detail.get("status"),
            "verdict": detail.get("verdict"),
            "gate": detail.get("gate"),
            "annotations": detail.get("annotations", []),
            "reasons": detail.get("reasons", []),
            "first_problem": first_problem,
        },
        "configuration": _provenance(detail),
        "steps": steps,
        "evidence_refs": [str(artifact.get("artifact_id")) for artifact in detail.get("artifacts", [])],
        "missing_evidence": [
            {"artifact_id": str(artifact.get("artifact_id")), "reason": artifact.get("unavailable_reason")}
            for artifact in detail.get("artifacts", [])
            if artifact.get("state") != "available"
        ],
        "generated_at": datetime.now(UTC).isoformat(),
    }
