from __future__ import annotations

from pathlib import Path

import pytest

from agentqa.platform.health import HealthService
from agentqa.platform.storage.database import create_engine
from agentqa.platform.storage.migrate import downgrade, upgrade
from agentqa.platform.storage.roles import ROLE_API, ROLE_MIGRATE, admin_dsn, create_database, drop_database, role_dsn

pytestmark = pytest.mark.asyncio


async def test_readiness_reports_layered_checks_without_model(runtime, api_client) -> None:
    response = await api_client.get("/health/ready")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ready"] is True
    checks = {check["name"]: check for check in body["checks"]}
    assert set(checks) == {"database", "schema", "storage", "queue", "providers"}
    assert checks["schema"]["detail"] == "ok"
    assert checks["providers"]["ok"] is True
    assert "không gọi model" in checks["providers"]["detail"]

    metrics = await api_client.get("/metrics")
    assert metrics.status_code == 200
    payload = metrics.json()
    assert payload["requests"]["requests_total"] >= 1
    text = metrics.text.lower()
    assert "password" not in text and "postgresql://" not in text

    echoed = await api_client.get("/health/ready", headers={"x-request-id": "corr-123"})
    assert echoed.headers["x-request-id"] == "corr-123"


async def test_readiness_fails_on_schema_mismatch(test_db, tmp_path: Path) -> None:
    import secrets

    name = f"agentqa_test_health_{secrets.token_hex(4)}"
    admin = admin_dsn()
    await create_database(admin, name)
    try:
        dsn = role_dsn(ROLE_MIGRATE, name)
        await upgrade(dsn)
        await downgrade(dsn, "-1")
        engine = create_engine(role_dsn(ROLE_API, name))
        try:
            service = HealthService({ROLE_API: engine}, artifact_root=tmp_path / "store")
            report = await service.ready()
            checks = {check.name: check for check in report.checks}
            assert report.ready is False
            assert checks["schema"].ok is False
            assert "lệch revision" in checks["schema"].detail
            assert checks["storage"].ok is True
        finally:
            await engine.dispose()
    finally:
        await drop_database(admin, name)


async def test_readiness_fails_without_storage_root(runtime) -> None:
    service = HealthService(runtime.engines, artifact_root=None)
    report = await service.ready()
    checks = {check.name: check for check in report.checks}
    assert checks["storage"].ok is False
    assert report.ready is False
