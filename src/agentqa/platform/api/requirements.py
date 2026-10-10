from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request

from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import authenticate, get_runtime, to_api_error
from agentqa.platform.identity.models import IdentityError, Permission

router = APIRouter(prefix="/api/v1", tags=["requirements"])


class ImpactLinkResponse(StrictModel):
    case_id: UUID
    logical_key: str
    case_revision_id: UUID
    revision_no: int
    needs_review: bool
    source_names: list[str]
    affected_assertions: list[str]
    affected_nodes: list[str]
    review_marked_at: datetime | None = None


class ImpactResponse(StrictModel):
    requirement_id: UUID
    logical_key: str
    latest_revision_no: int | None = None
    links: list[ImpactLinkResponse]


@router.get("/workspaces/{workspace_id}/requirements/{requirement_id}/impact", response_model=ImpactResponse)
async def requirement_impact(request: Request, workspace_id: UUID, requirement_id: UUID) -> ImpactResponse:
    principal = await authenticate(request)
    runtime = get_runtime(request)
    try:
        await runtime.authorization.require(
            workspace_id=workspace_id, user_id=principal.user_id, permission=Permission.WORKSPACE_READ
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    try:
        impact = await runtime.requirement_impact.impact(
            workspace_id=workspace_id, principal_id=principal.user_id, requirement_id=requirement_id
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return ImpactResponse(
        requirement_id=impact.requirement_id,
        logical_key=impact.logical_key,
        latest_revision_no=impact.latest_revision_no,
        links=[
            ImpactLinkResponse(
                case_id=link.case_id,
                logical_key=link.logical_key,
                case_revision_id=link.case_revision_id,
                revision_no=link.revision_no,
                needs_review=link.needs_review,
                source_names=link.source_names,
                affected_assertions=link.affected_assertions,
                affected_nodes=link.affected_nodes,
                review_marked_at=link.review_marked_at,
            )
            for link in impact.links
        ],
    )
