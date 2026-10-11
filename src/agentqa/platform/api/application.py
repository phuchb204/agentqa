from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from agentqa.contracts.errors import AgentQAValidationError, ErrorCode
from agentqa.platform.api.artifacts import router as artifacts_router
from agentqa.platform.api.auth import router as auth_router
from agentqa.platform.api.authoring import router as authoring_router
from agentqa.platform.api.bundles import router as bundles_router
from agentqa.platform.api.calibrations import router as calibrations_router
from agentqa.platform.api.controls import router as controls_router
from agentqa.platform.api.error_models import ApiError, ErrorResponse, FieldErrorModel, HealthResponse
from agentqa.platform.api.events import router as events_router
from agentqa.platform.api.experiments import router as experiments_router
from agentqa.platform.api.exploration import router as exploration_router
from agentqa.platform.api.health import router as health_router
from agentqa.platform.api.reports import router as reports_router
from agentqa.platform.api.requirements import router as requirements_router
from agentqa.platform.api.revisions import router as revisions_router
from agentqa.platform.api.runs import router as runs_router
from agentqa.platform.api.runtime import PlatformRuntime
from agentqa.platform.api.schedules import router as schedules_router
from agentqa.platform.api.schemas import (
    OPENAPI_PATH,
    PUBLIC_SCHEMAS,
    build_catalog,
    canonical_json_text,
    schema_document,
    schema_json_text,
)
from agentqa.platform.api.settings import router as settings_router
from agentqa.platform.api.sources import router as sources_router
from agentqa.platform.api.streams import router as streams_router
from agentqa.platform.api.webapp import SpaStaticFiles, web_dist_directory
from agentqa.platform.api.workspaces import router as workspaces_router

API_VERSION = "0.1.0"


def _response(status_code: int, error: ErrorResponse) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error.model_dump(mode="json"))


def _install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
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

    @app.exception_handler(AgentQAValidationError)
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

    @app.exception_handler(RequestValidationError)
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


def _health_live() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=API_VERSION,
        schema_versions={name: version for name, version in sorted(PUBLIC_SCHEMAS)},
    )


def _list_schemas(request: Request) -> dict[str, object]:
    artifacts = {path: schema_json_text(name, version) for (name, version), (path, _) in PUBLIC_SCHEMAS.items()}
    artifacts[OPENAPI_PATH] = canonical_json_text(request.app.openapi())
    return build_catalog(artifacts)


def _get_schema(name: str, version: str) -> dict[str, object]:
    if (name, version) not in PUBLIC_SCHEMAS:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message=f"Không có schema '{name}/{version}'",
        )
    return schema_document(name, version)


def create_application(runtime: PlatformRuntime | None = None) -> FastAPI:
    from agentqa.platform.telemetry import CorrelationMiddleware

    app = FastAPI(title="AgentQA API", version=API_VERSION, openapi_url="/api/v1/openapi.json")
    app.state.runtime = runtime
    app.add_middleware(CorrelationMiddleware)
    _install_handlers(app)
    app.include_router(auth_router)
    app.include_router(workspaces_router)
    app.include_router(runs_router)
    app.include_router(events_router)
    app.include_router(controls_router)
    app.include_router(sources_router)
    app.include_router(requirements_router)
    app.include_router(authoring_router)
    app.include_router(exploration_router)
    app.include_router(bundles_router)
    app.include_router(artifacts_router)
    app.include_router(streams_router)
    app.include_router(reports_router)
    app.include_router(calibrations_router)
    app.include_router(experiments_router)
    app.include_router(schedules_router)
    app.include_router(settings_router)
    app.include_router(health_router)
    app.include_router(revisions_router)
    app.add_api_route("/health/live", _health_live, methods=["GET"], response_model=HealthResponse)
    app.add_api_route("/api/v1/schemas", _list_schemas, methods=["GET"], response_model=None)
    app.add_api_route(
        "/api/v1/schemas/{name}/{version}",
        _get_schema,
        methods=["GET"],
        response_model=None,
        responses={404: {"model": ErrorResponse, "description": "Schema không tồn tại"}},
    )
    web_dist = web_dist_directory()
    if web_dist is not None:
        app.mount("/", SpaStaticFiles(directory=str(web_dist), html=True), name="web")
    return app


api = create_application()
