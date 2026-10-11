from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from infra.workloads.common import WorkloadContext

FAULT_ROUNDS = 3


class BrokenJournal:
    def __init__(self, journal) -> None:
        self._journal = journal

    def __getattr__(self, name: str):
        from agentqa.platform.supervisor import JournalUnavailable

        raise JournalUnavailable("db down")


def _command_state(env, command_id: UUID) -> str | None:
    from tests.support.faults import scoped_rows

    rows = scoped_rows(
        env.worker_dsn,
        env.workspace_id,
        env.user_id,
        "SELECT state FROM action_commands WHERE command_id = %s",
        (command_id,),
    )
    return rows[0][0] if rows else None


def _response_loss_round(env, server, namespace: str) -> dict[str, Any]:
    from tests.support.faults import execute_fields, literal, scoped_rows, start_supervisor, wait_for

    from agentqa.platform.fixtures import synthetic_password

    session_key = "w5-session-loss"
    item_name = "Việc w5 response loss"
    origin = f"127.0.0.1:{urlsplit(server.base_url).port}"
    proc = start_supervisor(
        dsn=env.supervisor_dsn,
        workspace_id=env.workspace_id,
        principal_id=env.user_id,
        run_id=env.run_id,
        attempt_id=env.attempt_id,
        session_key=session_key,
        allow_origins=[origin],
        lease_seconds=60,
    )
    result: dict[str, Any] = {"round": "response-loss", "namespace": namespace, "item_name": item_name}
    try:
        client = proc.client()
        client.open_session(session_key=session_key, run_id=env.run_id, attempt_id=env.attempt_id)
        client.execute(
            **execute_fields(
                env,
                session_key=session_key,
                operation="navigate",
                payload={"value": literal(f"{server.base_url}/{namespace}/login")},
            )
        )
        for payload in (
            {"target": {"intent": "username", "role": "textbox", "name": "Tài khoản"}, "value": literal("alice")},
            {
                "target": {"intent": "password", "locators": [{"kind": "label", "value": "Mật khẩu"}]},
                "value": literal(synthetic_password(namespace, "alice")),
            },
        ):
            client.execute(**execute_fields(env, session_key=session_key, operation="fill", payload=payload))
        client.execute(
            **execute_fields(
                env,
                session_key=session_key,
                operation="click",
                payload={"target": {"intent": "login", "role": "button", "name": "Đăng nhập"}},
            )
        )
        client.execute(
            **execute_fields(
                env,
                session_key=session_key,
                operation="fill",
                payload={
                    "target": {"intent": "new_item", "role": "textbox", "name": "Việc mới"},
                    "value": literal(item_name),
                },
            )
        )
        fields = execute_fields(
            env,
            session_key=session_key,
            operation="click",
            payload={"target": {"intent": "create", "role": "button", "name": "Thêm việc"}},
            side_effect="external_write",
        )
        command_id = UUID(fields["command_id"])
        client.send_without_reading({"op": "execute", **fields})
        client.close_socket()
        settled = wait_for(lambda: _command_state(env, command_id) == "settled", timeout=30)
        result["settled"] = bool(settled)
        time.sleep(0.5)
        reconnected = proc.client()
        duplicate = reconnected.execute(**fields)
        result["duplicate_state"] = duplicate["state"]
        rows = scoped_rows(
            env.worker_dsn,
            env.workspace_id,
            env.user_id,
            "SELECT count(*) FROM command_receipts WHERE command_id = %s AND state = 'settled'",
            (command_id,),
        )
        result["settled_receipts"] = int(rows[0][0])
    finally:
        proc.terminate()
    return result


def _login_and_crash_round(env, server, namespace: str, round_index: int) -> dict[str, Any]:
    from tests.support.faults import execute_fields, literal, start_supervisor, wait_for

    from agentqa.platform.fixtures import synthetic_password

    session_key = f"w5-session-{round_index}"
    item_name = f"Việc w5 round {round_index}"
    origin = f"127.0.0.1:{urlsplit(server.base_url).port}"
    proc = start_supervisor(
        dsn=env.supervisor_dsn,
        workspace_id=env.workspace_id,
        principal_id=env.user_id,
        run_id=env.run_id,
        attempt_id=env.attempt_id,
        session_key=session_key,
        allow_origins=[origin],
        lease_seconds=60,
        extra_args=["--fault-loss-intent=create"],
    )
    result: dict[str, Any] = {"round": round_index, "namespace": namespace}
    try:
        client = proc.client()
        client.open_session(session_key=session_key, run_id=env.run_id, attempt_id=env.attempt_id)
        result_navigate = client.execute(
            **execute_fields(
                env,
                session_key=session_key,
                operation="navigate",
                payload={"value": literal(f"{server.base_url}/{namespace}/login")},
            )
        )
        result["navigate"] = result_navigate["state"]
        for payload in (
            {"target": {"intent": "username", "role": "textbox", "name": "Tài khoản"}, "value": literal("alice")},
            {
                "target": {"intent": "password", "locators": [{"kind": "label", "value": "Mật khẩu"}]},
                "value": literal(synthetic_password(namespace, "alice")),
            },
        ):
            outcome = client.execute(**execute_fields(env, session_key=session_key, operation="fill", payload=payload))
            result["fill"] = outcome["state"]
        outcome = client.execute(
            **execute_fields(
                env,
                session_key=session_key,
                operation="click",
                payload={"target": {"intent": "login", "role": "button", "name": "Đăng nhập"}},
            )
        )
        result["login"] = outcome["state"]
        client.execute(
            **execute_fields(
                env,
                session_key=session_key,
                operation="fill",
                payload={
                    "target": {"intent": "new_item", "role": "textbox", "name": "Việc mới"},
                    "value": literal(item_name),
                },
            )
        )
        fields = execute_fields(
            env,
            session_key=session_key,
            operation="click",
            payload={"target": {"intent": "create", "role": "button", "name": "Thêm việc"}},
            side_effect="external_write",
        )
        command_id = UUID(fields["command_id"])
        client.send_without_reading({"op": "execute", **fields})
        observed = wait_for(
            lambda: _command_state(env, command_id) in ("dispatched", "unknown"),
            timeout=30,
        )
        result["loss_observed"] = bool(observed)
        time.sleep(1.0)
        proc.kill()
        result["command_id"] = str(command_id)
    finally:
        proc.terminate()
    result["item_name"] = item_name
    return result


async def run(ctx: WorkloadContext) -> dict[str, Any]:
    from tests.support.faults import FakeExecutor, build_fault_env, command_request
    from tests.support.taskboard import start_taskboard_server

    from agentqa.platform.artifacts.service import ArtifactService
    from agentqa.platform.artifacts.store import FaultBlobStore
    from agentqa.platform.fixtures import FixtureRegistry, TaskboardFixture
    from agentqa.platform.storage.roles import ROLE_API, ROLE_SUPERVISOR, ROLE_WORKER, role_dsn
    from agentqa.platform.supervisor import RuntimeConfig, SupervisorRuntime
    from agentqa.platform.supervisor.journal import StaleFence

    engines = ctx.engines
    supervisor_dsn = role_dsn(ROLE_SUPERVISOR, ctx.database)
    worker_dsn = role_dsn(ROLE_WORKER, ctx.database)
    checks: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    duplicate_effects = 0
    crash_results: list[dict[str, Any]] = []

    with start_taskboard_server() as server:
        registry = FixtureRegistry()
        registry.register(TaskboardFixture(server.base_url, server.control_token))
        for round_index in range(FAULT_ROUNDS):
            env = await build_fault_env(engines, supervisor_dsn, worker_dsn)
            namespace = f"w5-crash-{round_index}"
            assert registry.prepare("taskboard@1", namespace).ok
            result = await asyncio.to_thread(_login_and_crash_round, env, server, namespace, round_index)
            result["state_after_kill"] = _command_state(env, UUID(result["command_id"]))
            report = await env.recovery.reconcile_attempt(env.attempt_id)
            result["unknown_marked"] = (
                str(result["command_id"]) in {str(item) for item in report.unknown_command_ids}
                or _command_state(env, UUID(result["command_id"])) == "unknown"
            )
            await asyncio.sleep(1.0)
            probe_before = registry.probe("taskboard@1", namespace)
            count_before = int(probe_before["label_counts"].get(result["item_name"], 0))
            await asyncio.sleep(0.5)
            probe_after = registry.probe("taskboard@1", namespace)
            count_after = int(probe_after["label_counts"].get(result["item_name"], 0))
            result["effect_count_before"] = count_before
            result["effect_count_after"] = count_after
            if count_before > 1 or count_after != count_before:
                duplicate_effects += 1
            blocked = await env.recovery.retry_decision(env.attempt_id, fixture_reset_ok=False)
            result["retry_blocked_without_reset"] = blocked.allowed is False
            result["namespace_prepared"] = True
            crash_results.append(result)
            registry.reset("taskboard@1", namespace)

        loss_env = await build_fault_env(engines, supervisor_dsn, worker_dsn)
        loss_namespace = "w5-response-loss"
        assert registry.prepare("taskboard@1", loss_namespace).ok
        loss_result = await asyncio.to_thread(_response_loss_round, loss_env, server, loss_namespace)
        probe_loss = registry.probe("taskboard@1", loss_namespace)
        loss_count = int(probe_loss["label_counts"].get("Việc w5 response loss", 0))
        response_loss_ok = (
            loss_result["settled"]
            and loss_result["duplicate_state"] == "settled"
            and loss_result["settled_receipts"] == 1
            and loss_count == 1
        )

    crash_zero_duplicate = duplicate_effects == 0 and all(
        item["effect_count_before"] <= 1
        and item["effect_count_after"] == item["effect_count_before"]
        and item["unknown_marked"]
        for item in crash_results
    )
    retry_gate_ok = all(item["retry_blocked_without_reset"] for item in crash_results)
    checks.append(
        {
            "name": "crash_no_duplicate_effect",
            "ok": crash_zero_duplicate,
            "detail": f"rounds={len(crash_results)} duplicate_rounds={duplicate_effects}",
        }
    )
    checks.append(
        {
            "name": "unknown_blocks_retry_without_reset",
            "ok": retry_gate_ok,
            "detail": f"rounds_blocked={sum(1 for item in crash_results if item['retry_blocked_without_reset'])}",
        }
    )
    checks.append(
        {
            "name": "response_loss_single_effect",
            "ok": response_loss_ok,
            "detail": (
                f"count={loss_count} settled_receipts={loss_result['settled_receipts']} "
                f"duplicate={loss_result['duplicate_state']}"
            ),
        }
    )

    db_env = await build_fault_env(engines, supervisor_dsn, worker_dsn)
    executor = FakeExecutor()
    runtime = SupervisorRuntime(BrokenJournal(db_env.journal), executor, RuntimeConfig("w5-sup"))
    request = command_request(db_env, session_key="w5-db-down")
    receipt = await runtime.execute(request)
    db_ok = receipt.state == "rejected" and receipt.evidence == ["db_unavailable"] and executor.calls == []
    checks.append(
        {
            "name": "db_outage_no_side_effect",
            "ok": db_ok,
            "detail": f"state={receipt.state} calls={len(executor.calls)}",
        }
    )

    blob_root = ctx.profile_dir / "fault-blobs"
    store = FaultBlobStore(blob_root, fail_on_write=True)
    artifacts = ArtifactService(engines[ROLE_API], store)
    view = await artifacts.stage(
        workspace_id=db_env.workspace_id,
        principal_id=db_env.user_id,
        kind="evidence",
        media_type="image/png",
        payload=b"w5-partial-artifact",
        run_id=db_env.run_id,
    )
    blob_files = [path for path in blob_root.rglob("*") if path.is_file()]
    blob_ok = view.state == "unavailable" and view.unavailable_reason == "blob_write_failed" and not blob_files
    checks.append(
        {"name": "blob_fault_no_false_evidence", "ok": blob_ok, "detail": f"state={view.state} files={len(blob_files)}"}
    )

    fence_executor = FakeExecutor()
    fence_runtime = SupervisorRuntime(db_env.journal, fence_executor, RuntimeConfig("w5-fence"))
    await fence_runtime.open_session(
        run_id=db_env.run_id, attempt_id=db_env.attempt_id, session_key="w5-fence", fence_epoch=1
    )
    fence_request = command_request(db_env, session_key="w5-fence")
    settled = await fence_runtime.execute(fence_request)
    stale_blocked = False
    try:
        await db_env.journal.settle(fence_request.command_id, fence_epoch=2, outcome="succeeded", evidence=["stale"])
    except StaleFence:
        stale_blocked = True
    receipts = [r for r in await db_env.journal.receipts(db_env.attempt_id) if r.command_id == fence_request.command_id]
    fence_ok = stale_blocked and receipts[-1].state == "settled" and "stale" not in receipts[-1].evidence
    checks.append(
        {
            "name": "stale_fence_no_terminal_write",
            "ok": fence_ok and settled.state == "settled",
            "detail": f"stale_blocked={stale_blocked} last={receipts[-1].state}",
        }
    )

    claim = await db_env.queue.claim("w5-worker", lease_seconds=1)
    lease_ok = claim is not None
    if claim is not None:
        await asyncio.sleep(1.4)
        heartbeat = await db_env.queue.heartbeat(claim.lease_id)
        await db_env.queue.quarantine(claim.lease_id, reason="lease_lost")
        slot_state = await db_env.queue.slot_state()
        requeued = await db_env.queue.claim("w5-worker-2", lease_seconds=5)
        lease_ok = heartbeat is False and slot_state["reserved"] == 0 and requeued is None
    checks.append(
        {"name": "lease_loss_quarantine_no_requeue", "ok": lease_ok, "detail": f"claim_present={claim is not None}"}
    )

    ok = all(check["ok"] for check in checks)
    metrics = {
        "crash_rounds": crash_results,
        "duplicate_effects": duplicate_effects,
        "fault_checks": len(checks),
    }
    return {"ok": ok, "checks": checks, "metrics": metrics}
