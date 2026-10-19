from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import (
    GenerationMessage,
    GenerationMessageRole,
    GenerationRequest,
    GenerationTextPart,
    MessagePurpose,
    ModelCallOutcome,
    OutputFormat,
    ProviderRoute,
)
from agentqa.contracts.ports import GenerativeModelPort
from agentqa.models.wire import ModelTransportError
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.runs.read_models import RunReadModel
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope
from agentqa.platform.usage.service import UsageLedgerService

DIAGNOSTIC_LABEL = "Đề xuất phân tích"
DIAGNOSTIC_PROMPT_REF = "diagnostic/run-summary@1"


@dataclass(frozen=True)
class DiagnosticView:
    diagnostic_id: UUID
    run_id: UUID
    state: str
    label: str
    explanation: str | None
    confidence: Decimal | None
    evidence_refs: list[str]
    model_call_id: UUID | None
    created_at: datetime


def _view(row) -> DiagnosticView:
    return DiagnosticView(
        diagnostic_id=row.id,
        run_id=row.run_id,
        state=row.state,
        label=row.label,
        explanation=row.explanation,
        confidence=row.confidence,
        evidence_refs=list(row.evidence_refs or []),
        model_call_id=row.model_call_id,
        created_at=row.created_at,
    )


class DiagnosticService:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        model: GenerativeModelPort | None = None,
        usage: UsageLedgerService | None = None,
    ) -> None:
        self._engine = engine
        self._factory = create_session_factory(engine)
        self._model = model
        self._usage = usage or UsageLedgerService()

    async def create(self, *, workspace_id: UUID, principal_id: UUID, actor: str, run_id: UUID) -> DiagnosticView:
        detail = await RunReadModel(self._engine).run_detail(
            workspace_id=workspace_id, principal_id=principal_id, run_id=run_id
        )
        if detail is None:
            raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy run")
        if not detail["terminal"]:
            raise IdentityError(ErrorCode.INPUT_INVALID, "Diagnostic chỉ tạo sau khi run terminal")
        summary = _summary_payload(detail)
        explanation: str | None = None
        confidence: Decimal | None = None
        call_id: UUID | None = None
        state = "completed"
        if self._model is not None:
            async with self._factory() as session, session.begin():
                await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
                call_id = await self._usage.start_call(
                    session,
                    workspace_id=workspace_id,
                    route=getattr(self._model, "route", ProviderRoute.OPENCODE_GO),
                    purpose=MessagePurpose.DIAGNOSTIC,
                    requested_model=str(getattr(self._model, "_model", "") or "unknown"),
                )
            request = GenerationRequest(
                purpose=MessagePurpose.DIAGNOSTIC,
                schema_name="diagnostic",
                schema_version="1",
                prompt_ref=DIAGNOSTIC_PROMPT_REF,
                output_format=OutputFormat.JSON_OBJECT,
                messages=[
                    GenerationMessage(
                        role=GenerationMessageRole.USER,
                        parts=[
                            GenerationTextPart(
                                text=(
                                    "Phân tích nguyên nhân có thể của kết quả kiểm thử sau dưới dạng JSON "
                                    '{"explanation": "...", "confidence": 0.0-1.0}. '
                                    "Chỉ đề xuất, không kết luận thay verdict.\n"
                                    + json.dumps(summary, ensure_ascii=False, sort_keys=True)
                                )
                            )
                        ],
                    )
                ],
            )
            try:
                result = await self._model.generate(request)
                structured = result.structured or {}
                explanation = str(structured.get("explanation") or result.raw_text or "")
                raw_confidence = structured.get("confidence")
                if isinstance(raw_confidence, int | float) and not isinstance(raw_confidence, bool):
                    confidence = Decimal(str(round(float(raw_confidence), 4)))
                async with self._factory() as session, session.begin():
                    await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
                    await self._usage.settle_call(
                        session,
                        workspace_id=workspace_id,
                        call_id=call_id,
                        outcome=ModelCallOutcome.SUCCEEDED,
                        usage=result.usage,
                        resolved_model=result.model_resolved,
                    )
            except ModelTransportError as error:
                state = "failed"
                explanation = f"provider:{error.code.value}"
                async with self._factory() as session, session.begin():
                    await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
                    await self._usage.settle_call(
                        session,
                        workspace_id=workspace_id,
                        call_id=call_id,
                        outcome=ModelCallOutcome.FAILED,
                        usage=None,
                        error_code=error.code.value,
                    )
        evidence_refs = _evidence_refs(detail)
        diagnostic_id = uuid4()
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            row = (
                await session.execute(
                    sa.insert(tables.diagnostics)
                    .values(
                        id=diagnostic_id,
                        workspace_id=workspace_id,
                        run_id=run_id,
                        state=state,
                        label=DIAGNOSTIC_LABEL,
                        explanation=explanation,
                        confidence=confidence,
                        evidence_refs=evidence_refs,
                        model_call_id=call_id,
                        created_by=actor,
                    )
                    .returning(tables.diagnostics)
                )
            ).one()
        return _view(row)

    async def list_for_run(
        self, *, workspace_id: UUID, principal_id: UUID, run_id: UUID
    ) -> list[DiagnosticView] | None:
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
                    sa.select(tables.diagnostics)
                    .where(
                        tables.diagnostics.c.workspace_id == workspace_id,
                        tables.diagnostics.c.run_id == run_id,
                    )
                    .order_by(tables.diagnostics.c.created_at, tables.diagnostics.c.id)
                )
            ).all()
        return [_view(row) for row in rows]


def _summary_payload(detail: dict[str, Any]) -> dict[str, Any]:
    executions = detail.get("executions", [])
    first_problem = None
    for execution in executions:
        for assertion in execution.get("assertions", []):
            if assertion.get("result") in ("failed", "error"):
                first_problem = {
                    "checkpoint_id": assertion.get("checkpoint_id"),
                    "assertion_id": assertion.get("assertion_id"),
                    "result": assertion.get("result"),
                    "expected": assertion.get("proof", {}).get("expected"),
                    "observed": assertion.get("proof", {}).get("observed"),
                    "reason": assertion.get("proof", {}).get("reason"),
                }
                break
        if first_problem:
            break
    return {
        "status": detail.get("status"),
        "verdict": detail.get("verdict"),
        "gate": detail.get("gate"),
        "annotations": detail.get("annotations", []),
        "reasons": detail.get("reasons", []),
        "usage": detail.get("usage", {}),
        "first_problem": first_problem,
        "missing_artifacts": [
            artifact["artifact_id"] for artifact in detail.get("artifacts", []) if artifact.get("state") != "available"
        ],
    }


def _evidence_refs(detail: dict[str, Any]) -> list[str]:
    refs = [str(artifact["artifact_id"]) for artifact in detail.get("artifacts", [])]
    refs.extend(
        f"assertion:{execution.get('logical_key')}:{assertion.get('assertion_id')}"
        for execution in detail.get("executions", [])
        for assertion in execution.get("assertions", [])
    )
    return refs
