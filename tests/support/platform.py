from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import yaml

from agentqa.platform.api.runtime import PlatformRuntime
from agentqa.platform.revisions.service import PromotionReceipt
from agentqa.platform.runs.service import SubmitRequest

CASES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"


def case_content(logical_key: str = "start_flow") -> dict:
    document = yaml.safe_load((CASES_DIR / "valid_case_minimal.yaml").read_text(encoding="utf-8"))
    document["logical_key"] = logical_key
    return document


async def service_workspace(runtime: PlatformRuntime, *, label: str = "main") -> tuple[UUID, str, UUID]:
    suffix = uuid4().hex[:8]
    user = await runtime.users.create(username=f"{label}-{suffix}", password="pw-123456")
    workspace = await runtime.authorization.create_workspace(actor_id=user.id, slug=f"ws-{label}-{suffix}", name=label)
    return user.id, user.username, workspace.id


async def service_case_revision(
    runtime: PlatformRuntime,
    *,
    workspace_id: UUID,
    principal_id: UUID,
    actor: str,
    logical_key: str = "start_flow",
) -> PromotionReceipt:
    entity = await runtime.revisions.create_entity(
        workspace_id=workspace_id, principal_id=principal_id, kind="case", logical_key=logical_key
    )
    return await runtime.revisions.promote_content(
        workspace_id=workspace_id,
        principal_id=principal_id,
        actor=actor,
        kind="case",
        entity_id=entity.id,
        content=case_content(logical_key),
    )


def submit_request(
    *,
    workspace_id: UUID,
    principal_id: UUID,
    actor: str,
    revision_id: UUID,
    idempotency_key: str,
    environment_revision_id: UUID | None = None,
    provided_capabilities: frozenset[str] = frozenset(),
) -> SubmitRequest:
    return SubmitRequest(
        workspace_id=workspace_id,
        principal_id=principal_id,
        actor=actor,
        idempotency_key=idempotency_key,
        case_revision_ids=(revision_id,),
        environment_revision_id=environment_revision_id,
        provided_capabilities=provided_capabilities,
    )
