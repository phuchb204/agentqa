from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request

from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import authenticate, get_runtime, to_api_error
from agentqa.platform.calibration.service import CalibrationService, load_manifest
from agentqa.platform.identity.models import IdentityError, Permission

router = APIRouter(prefix="/api/v1", tags=["calibrations"])

MANIFEST_DIR = Path("benchmarks") / "calibration"


class CalibrationProfileStatus(StrictModel):
    profile_id: str
    version: str
    status: str
    reason: str | None = None
    production_ready: bool
    evidence: str | None = None
    bound_upper: float | None = None
    sample_units: int | None = None
    groups: int | None = None
    receipt_path: str | None = None
    manifest_digest: str


class CalibrationListResponse(StrictModel):
    items: list[CalibrationProfileStatus]


async def _require(request: Request, workspace_id: UUID):
    principal = await authenticate(request)
    runtime = get_runtime(request)
    try:
        await runtime.authorization.require(
            workspace_id=workspace_id, user_id=principal.user_id, permission=Permission.WORKSPACE_READ
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return principal


def _status_view(payload: dict[str, Any]) -> CalibrationProfileStatus:
    return CalibrationProfileStatus(
        profile_id=payload["profile_id"],
        version=payload["version"],
        status=payload["status"],
        reason=payload.get("reason"),
        production_ready=bool(payload.get("production_ready", False)),
        evidence=payload.get("evidence"),
        bound_upper=payload.get("bound_upper"),
        sample_units=payload.get("sample_units"),
        groups=payload.get("groups"),
        receipt_path=payload.get("receipt_path"),
        manifest_digest=payload["manifest_digest"],
    )


@router.get("/workspaces/{workspace_id}/calibrations", response_model=CalibrationListResponse)
async def list_calibrations(request: Request, workspace_id: UUID) -> CalibrationListResponse:
    await _require(request, workspace_id)
    items: list[CalibrationProfileStatus] = []
    manifest_dir = MANIFEST_DIR
    if manifest_dir.is_dir():
        for manifest_path in sorted(manifest_dir.glob("*.yaml")):
            manifest = load_manifest(manifest_path)
            service = CalibrationService(manifest)
            items.append(_status_view(service.status()))
    return CalibrationListResponse(items=items)
