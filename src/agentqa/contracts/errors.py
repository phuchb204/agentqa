from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class ErrorCode(StrEnum):
    INPUT_INVALID = "input_invalid"
    NOT_FOUND = "not_found"
    DUPLICATE_KEY = "duplicate_key"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    UNSUPPORTED_NODE = "unsupported_node"
    UNKNOWN_OPERATION = "unknown_operation"
    UNKNOWN_REFERENCE = "unknown_reference"
    DUPLICATE_ID = "duplicate_id"
    INVALID_CAPTURE = "invalid_capture"
    TYPE_MISMATCH = "type_mismatch"
    SECRET_INTERPOLATION = "secret_interpolation"
    SOURCE_UNCONFIRMED = "source_unconfirmed"
    EMPTY_ASSERTION = "empty_assertion"
    INCOMPLETE_BRANCH_PROOF = "incomplete_branch_proof"
    LOOP_BOUND_INVALID = "loop_bound_invalid"
    CAPABILITY_MISMATCH = "capability_mismatch"
    UNSAFE_JSON = "unsafe_json"
    SECRET_SERIALIZATION = "secret_serialization"
    DOCUMENT_TOO_LARGE = "document_too_large"
    ALIAS_LIMIT_EXCEEDED = "alias_limit_exceeded"
    CUSTOM_TAG_REJECTED = "custom_tag_rejected"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    PERMISSION_DENIED = "permission_denied"
    FIXTURE_FAILED = "fixture_failed"
    LOCATOR_MISSING = "locator_missing"
    LOCATOR_AMBIGUOUS = "locator_ambiguous"
    IDENTITY_MISMATCH = "identity_mismatch"
    ACTION_TIMEOUT = "action_timeout"
    ACTION_OUTCOME_UNKNOWN = "action_outcome_unknown"
    PROVIDER_AUTH = "provider_auth"
    PROVIDER_QUOTA = "provider_quota"
    PROVIDER_RATE_LIMIT = "provider_rate_limit"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_SCHEMA = "provider_schema"
    VERIFICATION_ERROR = "verification_error"
    EVIDENCE_MISSING = "evidence_missing"
    EVIDENCE_REDACTION_FAILED = "evidence_redaction_failed"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    LEASE_LOST = "lease_lost"
    WORKER_LOST = "worker_lost"
    RESOURCE_EXHAUSTED = "resource_exhausted"


ERROR_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.INPUT_INVALID: "Dữ liệu không hợp lệ",
    ErrorCode.NOT_FOUND: "Không tìm thấy tài nguyên",
    ErrorCode.DUPLICATE_KEY: "Khóa bị lặp trong tài liệu",
    ErrorCode.UNSUPPORTED_SCHEMA_VERSION: "Phiên bản schema không được hỗ trợ",
    ErrorCode.UNSUPPORTED_NODE: "Node DSL không được hỗ trợ",
    ErrorCode.UNKNOWN_OPERATION: "Thao tác không nằm trong registry",
    ErrorCode.UNKNOWN_REFERENCE: "Tham chiếu không resolve được",
    ErrorCode.DUPLICATE_ID: "Định danh bị trùng",
    ErrorCode.INVALID_CAPTURE: "Capture không hợp lệ",
    ErrorCode.TYPE_MISMATCH: "Kiểu dữ liệu không khớp",
    ErrorCode.SECRET_INTERPOLATION: "Secret không được dùng ở vị trí này",
    ErrorCode.SOURCE_UNCONFIRMED: "Nguồn suy luận chưa được xác nhận",
    ErrorCode.EMPTY_ASSERTION: "Assertion rỗng hoặc thiếu kỳ vọng",
    ErrorCode.INCOMPLETE_BRANCH_PROOF: "Nhánh không chứng minh đủ đường hoàn thành",
    ErrorCode.LOOP_BOUND_INVALID: "Bound của loop không hợp lệ",
    ErrorCode.CAPABILITY_MISMATCH: "Capability khai báo không khớp thao tác sử dụng",
    ErrorCode.UNSAFE_JSON: "JSON chứa giá trị không an toàn",
    ErrorCode.SECRET_SERIALIZATION: "Giá trị nhạy cảm không được serialize",
    ErrorCode.DOCUMENT_TOO_LARGE: "Tài liệu vượt giới hạn kích thước",
    ErrorCode.ALIAS_LIMIT_EXCEEDED: "Alias/anchor vượt giới hạn",
    ErrorCode.CUSTOM_TAG_REJECTED: "YAML tag tùy biến bị từ chối",
    ErrorCode.CAPABILITY_UNAVAILABLE: "Capability không khả dụng",
    ErrorCode.PERMISSION_DENIED: "Không đủ quyền",
    ErrorCode.FIXTURE_FAILED: "Fixture thất bại",
    ErrorCode.LOCATOR_MISSING: "Không tìm thấy target",
    ErrorCode.LOCATOR_AMBIGUOUS: "Target không duy nhất",
    ErrorCode.IDENTITY_MISMATCH: "Target không khớp identity",
    ErrorCode.ACTION_TIMEOUT: "Thao tác quá thời gian",
    ErrorCode.ACTION_OUTCOME_UNKNOWN: "Kết quả thao tác không xác định",
    ErrorCode.PROVIDER_AUTH: "Provider từ chối xác thực",
    ErrorCode.PROVIDER_QUOTA: "Provider hết quota",
    ErrorCode.PROVIDER_RATE_LIMIT: "Provider giới hạn tần suất",
    ErrorCode.PROVIDER_TIMEOUT: "Provider quá thời gian",
    ErrorCode.PROVIDER_SCHEMA: "Provider trả schema không hợp lệ",
    ErrorCode.VERIFICATION_ERROR: "Lỗi trong quá trình kiểm chứng",
    ErrorCode.EVIDENCE_MISSING: "Thiếu bằng chứng bắt buộc",
    ErrorCode.EVIDENCE_REDACTION_FAILED: "Redaction bằng chứng thất bại",
    ErrorCode.STORAGE_UNAVAILABLE: "Kho lưu trữ không khả dụng",
    ErrorCode.LEASE_LOST: "Mất lease",
    ErrorCode.WORKER_LOST: "Worker mất kết nối",
    ErrorCode.RESOURCE_EXHAUSTED: "Hết tài nguyên",
}


class FieldError(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: tuple[str | int, ...]
    code: ErrorCode
    message: str


def field_error(path: tuple[str | int, ...], code: ErrorCode, message: str | None = None) -> FieldError:
    return FieldError(path=path, code=code, message=message or ERROR_MESSAGES[code])


class AgentQAValidationError(Exception):
    def __init__(self, errors: list[FieldError]) -> None:
        self.errors = list(errors)
        super().__init__(f"{len(self.errors)} validation error(s)")

    def __str__(self) -> str:
        rendered = "; ".join(
            f"{'/'.join(str(part) for part in error.path)} [{error.code.value}]: {error.message}"
            for error in self.errors
        )
        return rendered or "validation failed"


KNOWN_SCHEMA_VERSIONS: dict[str, tuple[str, ...]] = {
    "case": ("1",),
    "run-event": ("1",),
}


MALFORMED_VERSION_MESSAGE = "Schema version sai định dạng"


def parse_schema_version(version: str) -> tuple[str, str]:
    if not isinstance(version, str) or version.count("/") != 1:
        raise AgentQAValidationError(
            [
                field_error(
                    ("schema_version",),
                    ErrorCode.UNSUPPORTED_SCHEMA_VERSION,
                    MALFORMED_VERSION_MESSAGE,
                )
            ]
        )
    name, revision = version.split("/", 1)
    if not name or not revision:
        raise AgentQAValidationError(
            [
                field_error(
                    ("schema_version",),
                    ErrorCode.UNSUPPORTED_SCHEMA_VERSION,
                    MALFORMED_VERSION_MESSAGE,
                )
            ]
        )
    return name, revision


def ensure_known_schema_version(version: str, field_path: tuple[str | int, ...] = ("schema_version",)) -> None:
    name, revision = parse_schema_version(version)
    known = KNOWN_SCHEMA_VERSIONS.get(name)
    if known is None or revision not in known:
        raise AgentQAValidationError(
            [
                field_error(
                    field_path,
                    ErrorCode.UNSUPPORTED_SCHEMA_VERSION,
                    f"Không hỗ trợ schema version '{version}'",
                )
            ]
        )


def upcast_document(version: str, document: Mapping[str, Any]) -> dict[str, Any]:
    ensure_known_schema_version(version)
    return dict(document)
