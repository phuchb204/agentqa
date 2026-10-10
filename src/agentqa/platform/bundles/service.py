from __future__ import annotations

import json
from uuid import UUID

import sqlalchemy as sa
import yaml
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.canonical import digest_content
from agentqa.contracts.compiler import parse_case_document
from agentqa.contracts.errors import AgentQAValidationError, ErrorCode
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.revisions.service import PromotionReceipt, RevisionService, validate_content
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope

BUNDLE_VERSION = "workspace-bundle/1"
REVISION_BUNDLE_VERSION = "revision-bundle/1"
MAX_BUNDLE_BYTES = 1_048_576
IMPORT_ORDER = ("requirement", "fixture", "case", "suite", "dataset")
BUNDLE_KINDS = ("requirement", "fixture", "case", "suite", "dataset")
FORBIDDEN_KEYS = (
    "credentials",
    "credential_refs",
    "credential_grants",
    "grants",
    "confirmation",
    "confirmation_ref",
    "approval",
    "approved",
    "lifecycle_approval",
)


class BundleService:
    def __init__(self, engine: AsyncEngine, *, revisions: RevisionService) -> None:
        self._factory = create_session_factory(engine)
        self._revisions = revisions

    async def export_workspace(self, *, workspace_id: UUID, principal_id: UUID, kinds: list[str] | None = None) -> dict:
        selected = list(kinds) if kinds else list(BUNDLE_KINDS)
        unknown = sorted(set(selected) - set(BUNDLE_KINDS))
        if unknown:
            raise IdentityError(ErrorCode.INPUT_INVALID, f"Kind không hỗ trợ: {', '.join(unknown)}")
        sections: dict[str, list] = {}
        for kind in selected:
            bundle = await self._revisions.export_bundle(
                workspace_id=workspace_id, principal_id=principal_id, kind=kind
            )
            sections[kind] = bundle["revisions"]
        return {"schema_version": BUNDLE_VERSION, "sections": sections}

    def export_text(self, bundle: dict, *, format: str = "yaml") -> str:
        if format == "json":
            return json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if format == "yaml":
            return yaml.safe_dump(bundle, allow_unicode=True, sort_keys=True)
        raise IdentityError(ErrorCode.INPUT_INVALID, f"Format không hỗ trợ: {format}")

    async def import_text(
        self, *, workspace_id: UUID, principal_id: UUID, actor: str, text: str
    ) -> list[PromotionReceipt]:
        document = self._parse(text)
        if document.get("schema_version") != BUNDLE_VERSION:
            raise IdentityError(ErrorCode.UNSUPPORTED_SCHEMA_VERSION, "Bundle version không hỗ trợ")
        sections = document.get("sections")
        if not isinstance(sections, dict):
            raise IdentityError(ErrorCode.INPUT_INVALID, "Bundle thiếu sections")
        planned: dict[str, list[dict]] = {}
        for kind, items in sections.items():
            if kind not in BUNDLE_KINDS:
                raise IdentityError(ErrorCode.INPUT_INVALID, f"Section không hỗ trợ: {kind}")
            if not isinstance(items, list):
                raise IdentityError(ErrorCode.INPUT_INVALID, f"Section '{kind}' phải là danh sách")
            for item in items:
                self._validate_item(kind, item)
            planned[kind] = items
        await self._check_bind(workspace_id=workspace_id, principal_id=principal_id, planned=planned)
        receipts: list[PromotionReceipt] = []
        for kind in IMPORT_ORDER:
            items = planned.get(kind)
            if not items:
                continue
            sub_bundle = {"schema_version": REVISION_BUNDLE_VERSION, "kind": kind, "revisions": items}
            receipts.extend(
                await self._revisions.import_bundle(
                    workspace_id=workspace_id, principal_id=principal_id, actor=actor, bundle=sub_bundle
                )
            )
        return receipts

    def _parse(self, text: str) -> dict:
        raw = text.encode("utf-8")
        if len(raw) > MAX_BUNDLE_BYTES:
            raise IdentityError(ErrorCode.DOCUMENT_TOO_LARGE, "Bundle vượt quá giới hạn dung lượng")
        stripped = text.lstrip()
        try:
            document = json.loads(text) if stripped.startswith("{") else parse_case_document(text)
        except AgentQAValidationError as error:
            raise IdentityError(
                ErrorCode.INPUT_INVALID, error.errors[0].message if error.errors else "Bundle không parse an toàn được"
            ) from error
        except ValueError as error:
            raise IdentityError(ErrorCode.INPUT_INVALID, "Bundle không parse được") from error
        if not isinstance(document, dict):
            raise IdentityError(ErrorCode.INPUT_INVALID, "Bundle phải là object")
        return document

    def _validate_item(self, kind: str, item: object) -> None:
        if not isinstance(item, dict):
            raise IdentityError(ErrorCode.INPUT_INVALID, "Revision trong bundle phải là object")
        forbidden = sorted(key for key in FORBIDDEN_KEYS if key in item)
        content = item.get("content")
        if isinstance(content, dict):
            forbidden.extend(key for key in FORBIDDEN_KEYS if key in content and key not in forbidden)
        if forbidden:
            raise IdentityError(
                ErrorCode.PERMISSION_DENIED,
                f"Bundle chứa trường quyền/credential không được import: {', '.join(sorted(set(forbidden)))}",
            )
        if not isinstance(content, dict):
            raise IdentityError(ErrorCode.INPUT_INVALID, "Revision content phải là object")
        expected = item.get("content_digest")
        if expected and digest_content(content) != expected:
            raise IdentityError(ErrorCode.INPUT_INVALID, "Content digest không khớp")
        validate_content(kind, content)

    async def _check_bind(self, *, workspace_id: UUID, principal_id: UUID, planned: dict[str, list[dict]]) -> None:
        planned_cases = {item.get("logical_key") for item in planned.get("case", [])}
        planned_datasets = {item.get("logical_key") for item in planned.get("dataset", [])}
        suite_items = planned.get("suite", [])
        if not suite_items:
            return
        facts: list[str] = []
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            for item in suite_items:
                content = item["content"]
                for ref in content.get("case_refs", []):
                    key = ref.get("logical_key")
                    revision_no = int(ref.get("revision_no", 1))
                    if key in planned_cases:
                        continue
                    row = (
                        await session.execute(
                            sa.select(tables.cases.c.id).where(
                                tables.cases.c.workspace_id == workspace_id,
                                tables.cases.c.logical_key == key,
                            )
                        )
                    ).one_or_none()
                    if row is None:
                        facts.append(f"missing_case:{key}")
                        continue
                    latest = (
                        await session.execute(
                            sa.select(sa.func.max(tables.case_revisions.c.revision_no)).where(
                                tables.case_revisions.c.workspace_id == workspace_id,
                                tables.case_revisions.c.case_id == row.id,
                            )
                        )
                    ).scalar_one_or_none()
                    if latest is None or int(latest) < revision_no:
                        facts.append(f"missing_case_revision:{key}@{revision_no}")
                dataset_ref = content.get("dataset_ref")
                if dataset_ref and dataset_ref not in planned_datasets:
                    row = (
                        await session.execute(
                            sa.select(tables.datasets.c.id).where(
                                tables.datasets.c.workspace_id == workspace_id,
                                tables.datasets.c.logical_key == dataset_ref,
                            )
                        )
                    ).one_or_none()
                    if row is None:
                        facts.append(f"missing_dataset:{dataset_ref}")
        if facts:
            raise IdentityError(
                ErrorCode.CAPABILITY_UNAVAILABLE,
                "Suite bind không đủ điều kiện: " + ", ".join(sorted(facts)),
            )
