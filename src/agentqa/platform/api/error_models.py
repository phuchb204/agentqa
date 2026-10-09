from __future__ import annotations

from pydantic import Field

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.values import StrictModel


class FieldErrorModel(StrictModel):
    path: tuple[str | int, ...]
    code: ErrorCode
    message: str


class ErrorResponse(StrictModel):
    code: ErrorCode
    message: str
    field_errors: list[FieldErrorModel] = []
    request_id: str | None = None
    retryable: bool = False


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        field_errors: list[FieldErrorModel] | None = None,
        retryable: bool = False,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field_errors = field_errors or []
        self.retryable = retryable
        super().__init__(message)


class HealthResponse(StrictModel):
    status: str = Field(pattern=r"^ok$")
    version: str
    schema_versions: dict[str, str] = {}
