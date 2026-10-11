from __future__ import annotations

import asyncio
import secrets
from typing import Any

from infra.workloads.common import WorkloadContext


async def run(ctx: WorkloadContext) -> dict[str, Any]:
    from tests.support.postgres import seed_workspace
    from tests.support.taskboard import TaskboardHttp, start_taskboard_server

    from agentqa.contracts.canonical import digest_artifact_bytes
    from agentqa.platform.artifacts.service import ArtifactService
    from agentqa.platform.artifacts.store import FaultBlobStore, FileSystemBlobStore
    from agentqa.platform.backup import BackupService
    from agentqa.platform.fixtures import FixtureRegistry, TaskboardFixture, synthetic_password
    from agentqa.platform.identity.models import IdentityError
    from agentqa.platform.storage.migrate import alembic_head_revision
    from agentqa.platform.storage.roles import ROLE_API, ROLE_MIGRATE, admin_dsn, drop_database, role_dsn

    engines = ctx.engines
    user_a, workspace_a = await seed_workspace(engines, label="w6-a")
    user_b, workspace_b = await seed_workspace(engines, label="w6-b")
    checks: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}

    with start_taskboard_server() as server:
        registry = FixtureRegistry()
        registry.register(TaskboardFixture(server.base_url, server.control_token))
        namespaces = ("w6-alpha", "w6-beta")
        prepared = await asyncio.gather(
            *(asyncio.to_thread(registry.prepare, "taskboard@1", namespace) for namespace in namespaces)
        )
        namespace_ok = all(receipt.ok for receipt in prepared)

        def _seed_items() -> None:
            alpha = TaskboardHttp(server.base_url)
            alpha.login("w6-alpha", "alice", synthetic_password("w6-alpha", "alice"))
            alpha.create_item("w6-alpha", "viet-a-1")
            alpha.create_item("w6-alpha", "viet-a-2")
            beta = TaskboardHttp(server.base_url)
            beta.login("w6-beta", "alice", synthetic_password("w6-beta", "alice"))
            beta.create_item("w6-beta", "viet-b-1")

        await asyncio.to_thread(_seed_items)
        probe_alpha = await asyncio.to_thread(registry.probe, "taskboard@1", "w6-alpha")
        probe_beta = await asyncio.to_thread(registry.probe, "taskboard@1", "w6-beta")
        isolated = (
            namespace_ok
            and probe_alpha["item_count"] == 2
            and probe_beta["item_count"] == 1
            and "viet-b-1" not in probe_alpha["label_counts"]
            and "viet-a-1" not in probe_beta["label_counts"]
        )
        await asyncio.to_thread(registry.reset, "taskboard@1", "w6-alpha")
        probe_alpha_after = await asyncio.to_thread(registry.probe, "taskboard@1", "w6-alpha")
        probe_beta_after = await asyncio.to_thread(registry.probe, "taskboard@1", "w6-beta")
        reset_isolated = probe_alpha_after["item_count"] == 0 and probe_beta_after["item_count"] == 1
        checks.append(
            {
                "name": "namespace_isolation",
                "ok": isolated and reset_isolated,
                "detail": (
                    f"alpha={probe_alpha['item_count']} beta={probe_beta['item_count']} "
                    f"after_reset alpha={probe_alpha_after['item_count']} beta={probe_beta_after['item_count']}"
                ),
            }
        )

    store_root = ctx.profile_dir / "blobs"
    store = FileSystemBlobStore(store_root)
    artifacts = ArtifactService(engines[ROLE_API], store)
    payload = b"w6-evidence-bytes"
    available = await artifacts.stage(
        workspace_id=workspace_a,
        principal_id=user_a,
        kind="screenshot",
        media_type="image/png",
        payload=payload,
    )
    tombstoned = await artifacts.tombstone(
        workspace_id=workspace_a, principal_id=user_a, artifact_id=available.id, reason="retention_expired"
    )
    stored = await ArtifactService(engines[ROLE_API], store).stage(
        workspace_id=workspace_a,
        principal_id=user_a,
        kind="trace",
        media_type="application/json",
        payload=b"w6-trace",
    )
    fault_store = FaultBlobStore(ctx.profile_dir / "blobs-fault", fail_on_write=True)
    failed = await ArtifactService(engines[ROLE_API], fault_store).stage(
        workspace_id=workspace_a,
        principal_id=user_a,
        kind="evidence",
        media_type="image/png",
        payload=b"w6-unavailable",
    )
    reconcile = await artifacts.reconcile(workspace_id=workspace_a, principal_id=user_a)
    digest_ok = available.digest == digest_artifact_bytes(payload) and tombstoned.digest == available.digest
    tombstone_ok = tombstoned.state == "deleted" and tombstoned.unavailable_reason == "retention_expired"
    failed_ok = failed.state == "unavailable" and failed.unavailable_reason == "blob_write_failed"
    reconcile_ok = reconcile.scanned == 0 and reconcile.published == 0
    checks.append(
        {
            "name": "artifact_retention_digests",
            "ok": digest_ok and tombstone_ok and failed_ok and reconcile_ok and stored.state == "available",
            "detail": (
                f"digest_ok={digest_ok} tombstone={tombstoned.state}/{tombstoned.unavailable_reason} "
                f"failed={failed.state}/{failed.unavailable_reason}"
            ),
        }
    )

    cross_denied = False
    try:
        await artifacts.get_authorized(workspace_id=workspace_b, principal_id=user_b, artifact_id=stored.id)
    except IdentityError:
        cross_denied = True
    try:
        await artifacts.open_bytes(workspace_id=workspace_b, principal_id=user_b, artifact_id=stored.id)
    except IdentityError:
        cross_denied = cross_denied and True
    else:
        cross_denied = False
    checks.append({"name": "cross_workspace_denied", "ok": cross_denied, "detail": f"denied={cross_denied}"})

    backup_dir = ctx.profile_dir / "backup"
    service = BackupService(admin_dsn(ctx.database), artifact_root=store.root)
    manifest = await service.create(backup_dir)
    service.verify(backup_dir)
    restore_database = f"agentqa_workload_restore_{secrets.token_hex(4)}"
    try:
        report = await service.restore(
            backup_dir, database=restore_database, migrate_dsn=role_dsn(ROLE_MIGRATE, restore_database)
        )
    finally:
        await drop_database(admin_dsn(), restore_database)
    backup_ok = (
        manifest.schema_version == alembic_head_revision()
        and report.failures == []
        and report.links_ok is True
        and report.table_counts["workspaces"] >= manifest.table_counts["workspaces"]
        and report.table_counts["artifacts"] == manifest.table_counts["artifacts"]
    )
    checks.append(
        {
            "name": "backup_restore_links",
            "ok": backup_ok,
            "detail": (
                f"schema={manifest.schema_version} failures={report.failures} "
                f"links_ok={report.links_ok} artifacts={manifest.table_counts['artifacts']}"
            ),
        }
    )

    ok = all(check["ok"] for check in checks)
    metrics = {
        "namespaces": list(namespaces),
        "artifacts_backed_up": manifest.table_counts.get("artifacts"),
        "restore_table_counts": {key: int(value) for key, value in report.table_counts.items()},
    }
    return {"ok": ok, "checks": checks, "metrics": metrics}
