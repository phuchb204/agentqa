from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
import yaml
from oracle.publish import publish_records
from oracle.registry import RECORDS, record_for, registry_digest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine

from agentqa.platform.fixtures import CanvasdeskFixture, ShopflowFixture, canvasdesk_password, shopflow_password
from agentqa.platform.storage.roles import ORACLE_DATABASE, ROLE_API, ROLE_WORKER, role_dsn
from tests.support.postgres import test_db as test_db

REPO_ROOT = Path(__file__).resolve().parents[2]
OPAQUE_REF = re.compile(r"^(sf|cd)-[0-9a-f]{16}$")
PRIVATE_IMPORT = re.compile(r"^\s*(?:from|import)\s+oracle\b", re.MULTILINE)


def test_worker_and_api_build_material_exclude_private_oracle() -> None:
    worker_files = [
        REPO_ROOT / "infra" / "Dockerfile.worker",
        REPO_ROOT / "infra" / "Dockerfile.worker.dockerignore",
        REPO_ROOT / "infra" / "compose.local.yml",
        REPO_ROOT / "infra" / "compose.test.yml",
    ]
    for path in worker_files:
        text = path.read_text(encoding="utf-8")
        assert "benchmarks/private" not in text, f"{path.name} tham chiếu private oracle"
        assert "oracle" not in text.lower(), f"{path.name} chứa truth/oracle path"
    dockerignore = (REPO_ROOT / "infra" / "Dockerfile.worker.dockerignore").read_text(encoding="utf-8")
    assert "!benchmarks/private" not in dockerignore


def test_runtime_sources_never_import_private_oracle() -> None:
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "src" / "agentqa").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "benchmarks/private" in text or PRIVATE_IMPORT.search(text):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert offenders == []


def test_sensors_return_opaque_refs_resolved_only_by_oracle(
    shopflow_fixture: ShopflowFixture, canvasdesk_fixture: CanvasdeskFixture
) -> None:
    from oracle.registry import resolve_ref

    namespace = "oracle-opaque"
    assert shopflow_fixture.prepare(namespace).ok
    with httpx.Client(base_url=shopflow_fixture.base_url, follow_redirects=True, timeout=10.0) as client:
        client.post(
            f"/{namespace}/login",
            data={"username": "alice", "password": shopflow_password(namespace, "alice")},
        )
        client.post(f"/{namespace}/cart/lines", data={"product_id": "sp-1", "qty": 1})
    shopflow_probe = shopflow_fixture.probe(namespace)
    ref = shopflow_probe["last_write_ref"]
    assert OPAQUE_REF.match(ref), ref
    assert ref != "line-1"
    assert resolve_ref("shopflow", namespace, ref) == "line-1"

    canvas_namespace = "oracle-canvas"
    assert canvasdesk_fixture.prepare(canvas_namespace).ok
    with httpx.Client(base_url=canvasdesk_fixture.base_url, follow_redirects=True, timeout=10.0) as client:
        client.post(
            f"/{canvas_namespace}/login",
            data={"username": "alice", "password": canvasdesk_password(canvas_namespace, "alice")},
        )
        client.post(f"/{canvas_namespace}/board/select", data={"cell_id": "cell-2"})
    canvas_probe = canvasdesk_fixture.probe(canvas_namespace)
    selected_ref = canvas_probe["selected_ref"]
    assert OPAQUE_REF.match(selected_ref), selected_ref
    assert selected_ref != "cell-2"
    assert resolve_ref("canvasdesk", canvas_namespace, selected_ref) == "cell-2"


def test_registry_covers_every_public_case_with_stable_digest() -> None:
    inventory = yaml.safe_load((REPO_ROOT / "benchmarks" / "public" / "inventory.yaml").read_text(encoding="utf-8"))
    case_keys = set()
    for case_rel in inventory["cases"]:
        document = yaml.safe_load((REPO_ROOT / case_rel).read_text(encoding="utf-8"))
        case_keys.add(document["logical_key"])
    for key in case_keys:
        assert record_for(key) is not None, f"thiếu oracle record cho {key}"
    assert registry_digest() == registry_digest()
    assert len(registry_digest()) == 64


@pytest.mark.asyncio
async def test_oracle_records_publish_readable_only_by_evaluator_role(test_db) -> None:
    from agentqa.platform.storage.roles import ROLE_EVALUATOR

    evaluator_dsn = role_dsn(ROLE_EVALUATOR, ORACLE_DATABASE)
    published = await publish_records(evaluator_dsn)
    assert published == len(RECORDS)

    engine = create_async_engine(evaluator_dsn)
    try:
        async with engine.connect() as connection:
            count = (await connection.execute(sa.text("SELECT count(*) FROM oracle_records"))).scalar_one()
            digest = (
                await connection.execute(
                    sa.text("SELECT payload_digest FROM oracle_records WHERE logical_key = 'shopflow_search_filter'")
                )
            ).scalar_one()
        assert count == len(RECORDS)
        assert len(digest) == 64
    finally:
        await engine.dispose()

    for role in (ROLE_WORKER, ROLE_API):
        blocked = create_async_engine(role_dsn(role, ORACLE_DATABASE))
        try:
            with pytest.raises(OperationalError):
                async with blocked.connect() as connection:
                    await connection.execute(sa.text("SELECT 1"))
        finally:
            await blocked.dispose()
