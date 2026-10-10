from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import get_runtime
from agentqa.platform.health import HealthService
from agentqa.platform.storage.roles import ROLE_API
from agentqa.platform.telemetry import request_metrics_snapshot

router = APIRouter(tags=["health"])


class CheckModel(StrictModel):
    name: str
    ok: bool
    detail: str


class ReadinessResponse(StrictModel):
    status: str
    ready: bool
    checks: list[CheckModel]


@router.get("/health/ready")
async def health_ready(request: Request) -> JSONResponse:
    runtime = get_runtime(request)
    service = HealthService(runtime.engines, artifact_root=runtime.artifacts.store.root)
    report = await service.ready()
    body = ReadinessResponse(
        status="ok" if report.ready else "unavailable",
        ready=report.ready,
        checks=[CheckModel(name=check.name, ok=check.ok, detail=check.detail) for check in report.checks],
    )
    return JSONResponse(status_code=200 if report.ready else 503, content=body.model_dump(mode="json"))


@router.get("/metrics")
async def metrics(request: Request) -> dict[str, object]:
    runtime = get_runtime(request)
    engine = runtime.engines[ROLE_API]
    estimates: dict[str, int] = {}
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT relname, GREATEST(reltuples, 0) AS estimate FROM pg_class "
                        "WHERE relname IN ('jobs', 'runs', 'executions', 'schedule_occurrences', 'outbox_deliveries')"
                    )
                )
            ).all()
        estimates = {row.relname: int(row.estimate) for row in rows}
    except Exception:
        estimates = {}
    return {
        "requests": request_metrics_snapshot(),
        "table_estimates": estimates,
    }
