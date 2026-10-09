from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from agentqa.contracts.capabilities import (
    CAPABILITY_SCHEMA_VERSION,
    CapabilityKind,
    CapabilityReceipt,
    CapabilityStatus,
)
from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import ProviderRoute

DIGEST_PATTERN = "^[0-9a-f]{64}$"
FORBIDDEN_KEYS = ("api_key", "authorization", "token", "password", "secret", "bearer")
SUPPORTED_RECEIPT_VERSIONS = (CAPABILITY_SCHEMA_VERSION,)


class ReceiptError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def migrate_receipt_document(document: dict) -> dict:
    version = document.get("schema_version")
    if version not in SUPPORTED_RECEIPT_VERSIONS:
        raise ReceiptError(ErrorCode.UNSUPPORTED_SCHEMA_VERSION, f"Receipt version không hỗ trợ: {version!r}")
    return dict(document)


def parse_receipt(document: dict) -> CapabilityReceipt:
    _reject_unsafe_keys(document)
    migrated = migrate_receipt_document(document)
    try:
        receipt = CapabilityReceipt.model_validate(migrated)
    except Exception as error:
        raise ReceiptError(ErrorCode.INPUT_INVALID, "Receipt không hợp lệ") from error
    for digest in (receipt.request_digest, receipt.result_digest):
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ReceiptError(ErrorCode.INPUT_INVALID, "Receipt digest phải là sha256 hex")
    if receipt.blocked_reason is None and any(
        status in (CapabilityStatus.BLOCKED, CapabilityStatus.UNSUPPORTED) for status in receipt.capabilities.values()
    ):
        raise ReceiptError(ErrorCode.INPUT_INVALID, "Receipt blocked/unsupported phải có reason")
    return receipt


def _reject_unsafe_keys(payload: object) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            if any(forbidden in lowered for forbidden in FORBIDDEN_KEYS):
                raise ReceiptError(ErrorCode.SECRET_SERIALIZATION, f"Receipt chứa trường cấm: {key}")
            _reject_unsafe_keys(value)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            _reject_unsafe_keys(item)


class CapabilityReceiptStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def save(self, receipt: CapabilityReceipt) -> Path:
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / f"{receipt.route.value}-{receipt.receipt_id}.json"
        path.write_text(
            json.dumps(receipt.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="\n",
        )
        return path

    def load_all(self) -> list[CapabilityReceipt]:
        if not self._root.is_dir():
            return []
        receipts: list[CapabilityReceipt] = []
        for path in sorted(self._root.glob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            receipts.append(parse_receipt(document))
        return receipts

    def latest(self, *, route: ProviderRoute, model: str) -> CapabilityReceipt | None:
        matching = [
            receipt for receipt in self.load_all() if receipt.route is route and receipt.model_requested == model
        ]
        if not matching:
            return None
        return max(matching, key=lambda receipt: receipt.verified_at)

    def status(
        self,
        *,
        route: ProviderRoute,
        model: str,
        kind: CapabilityKind,
        now: datetime | None = None,
    ) -> CapabilityStatus:
        moment = now or datetime.now(UTC)
        receipt = self.latest(route=route, model=model)
        if receipt is None:
            return CapabilityStatus.UNVERIFIED
        if not receipt.is_valid_at(moment):
            return CapabilityStatus.BLOCKED
        return receipt.capability_status(kind)

    def image_gate(self, *, route: ProviderRoute, model: str, now: datetime | None = None) -> CapabilityStatus:
        return self.status(route=route, model=model, kind=CapabilityKind.IMAGE, now=now)


def route_epoch(route: ProviderRoute, model: str, *, day: str | None = None) -> str:
    stamp = day or datetime.now(UTC).date().isoformat()
    return sha256(f"{route.value}|{model}|{stamp}".encode()).hexdigest()[:16]


def request_digest(payload: object) -> str:
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def result_digest(payload: object) -> str:
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


__all__ = [
    "CapabilityReceiptStore",
    "ReceiptError",
    "migrate_receipt_document",
    "parse_receipt",
    "request_digest",
    "result_digest",
    "route_epoch",
]
