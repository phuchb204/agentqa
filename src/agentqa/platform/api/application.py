from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from agentqa.contracts.errors import AgentQAValidationError, ErrorCode
from agentqa.platform.api.error_models import ApiError, ErrorResponse, FieldErrorModel, HealthResponse
from agentqa.platform.api.schemas import (
    OPENAPI_PATH,
    PUBLIC_SCHEMAS,
    build_catalog,
    canonical_json_text,
    schema_document,
    schema_json_text,
)

API_VERSION = "0.1.0"

api = FastAPI(title="AgentQA API", version=API_VERSION, openapi_url="/api/v1/openapi.json")


def _response(status_code: int, error: ErrorResponse) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error.model_dump(mode="json"))


@api.exception_handler(ApiError)
async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
    return _response(
        exc.status_code,
        ErrorResponse(
            code=exc.code,
            message=exc.message,
            field_errors=exc.field_errors,
            request_id=request.headers.get("x-request-id"),
            retryable=exc.retryable,
        ),
    )


@api.exception_handler(AgentQAValidationError)
async def handle_validation_error(request: Request, exc: AgentQAValidationError) -> JSONResponse:
    return _response(
        422,
        ErrorResponse(
            code=ErrorCode.INPUT_INVALID,
            message="Dữ liệu không hợp lệ",
            field_errors=[
                FieldErrorModel(path=error.path, code=error.code, message=error.message) for error in exc.errors
            ],
            request_id=request.headers.get("x-request-id"),
        ),
    )


@api.exception_handler(RequestValidationError)
async def handle_request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    field_errors = [
        FieldErrorModel(
            path=tuple(part for part in error.get("loc", ()) if part != "body"),
            code=ErrorCode.INPUT_INVALID,
            message="Dữ liệu không hợp lệ",
        )
        for error in exc.errors()
    ]
    return _response(
        422,
        ErrorResponse(
            code=ErrorCode.INPUT_INVALID,
            message="Dữ liệu không hợp lệ",
            field_errors=field_errors,
            request_id=request.headers.get("x-request-id"),
        ),
    )


@api.get("/health/live", response_model=HealthResponse)
def health_live() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=API_VERSION,
        schema_versions={name: version for name, version in sorted(PUBLIC_SCHEMAS)},
    )


@api.get("/api/v1/schemas", response_model=None)
def list_schemas() -> dict[str, object]:
    artifacts = {path: schema_json_text(name, version) for (name, version), (path, _) in PUBLIC_SCHEMAS.items()}
    artifacts[OPENAPI_PATH] = canonical_json_text(api.openapi())
    return build_catalog(artifacts)


@api.get(
    "/api/v1/schemas/{name}/{version}",
    response_model=None,
    responses={404: {"model": ErrorResponse, "description": "Schema không tồn tại"}},
)
def get_schema(name: str, version: str) -> dict[str, object]:
    if (name, version) not in PUBLIC_SCHEMAS:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message=f"Không có schema '{name}/{version}'",
        )
    return schema_document(name, version)
