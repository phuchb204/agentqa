from __future__ import annotations

import asyncio
from urllib.parse import urlsplit
from uuid import UUID

import pytest

from agentqa.platform.fixtures import FixtureRegistry, synthetic_password
from tests.support.faults import execute_fields, literal, scoped_rows, start_supervisor, wait_for
from tests.support.taskboard import TaskboardServer

pytestmark = pytest.mark.asyncio


def run_command(client, env, session_key: str, operation: str, payload: dict, side_effect: str = "read") -> dict:
    fields = execute_fields(
        env,
        session_key=session_key,
        operation=operation,
        payload=payload,
        side_effect=side_effect,
    )
    return client.execute(**fields)


def login_flow(client, env, taskboard_server: TaskboardServer, namespace: str, session_key: str) -> None:
    result = run_command(
        client,
        env,
        session_key,
        "navigate",
        {"value": literal(f"{taskboard_server.base_url}/{namespace}/login")},
    )
    assert result["state"] == "settled"
    assert result["outcome"] == "succeeded"
    for target, value in (
        ({"intent": "username", "role": "textbox", "name": "Tài khoản"}, literal("alice")),
        (
            {"intent": "password", "locators": [{"kind": "label", "value": "Mật khẩu"}]},
            literal(synthetic_password(namespace, "alice")),
        ),
    ):
        result = run_command(client, env, session_key, "fill", {"target": target, "value": value})
        assert result["state"] == "settled", result
    result = run_command(
        client, env, session_key, "click", {"target": {"intent": "login", "role": "button", "name": "Đăng nhập"}}
    )
    assert result["state"] == "settled", result


async def test_kill_after_dispatch_marks_unknown_without_redispatch(
    fault_env, taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry
) -> None:
    env = fault_env
    namespace = "crash-effect"
    assert fixture_registry.prepare("taskboard@1", namespace).ok
    origin = f"127.0.0.1:{urlsplit(taskboard_server.base_url).port}"
    session_key = "crash-session"
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
    try:
        client = proc.client()
        client.open_session(session_key=session_key, run_id=env.run_id, attempt_id=env.attempt_id)
        login_flow(client, env, taskboard_server, namespace, session_key)
        run_command(
            client,
            env,
            session_key,
            "fill",
            {
                "target": {"intent": "new_item", "role": "textbox", "name": "Việc mới"},
                "value": literal("slow-Việc crash"),
            },
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
        dispatched = wait_for(
            lambda: _command_state(env, command_id) == "dispatched",
            timeout=20,
        )
        assert dispatched, f"state={_command_state(env, command_id)} stderr={proc.stderr_text()[:2000]}"
        proc.kill()

        assert _command_state(env, command_id) == "dispatched"
        report = await env.recovery.reconcile_attempt(env.attempt_id)
        assert command_id in report.unknown_command_ids
        receipts = [r for r in await env.journal.receipts(env.attempt_id) if r.command_id == command_id]
        assert [r.state for r in receipts] == ["accepted", "dispatched", "unknown"]
        assert receipts[-1].reason == "owner_lost_reconciliation"

        await asyncio.sleep(1.2)
        first = fixture_registry.probe("taskboard@1", namespace)
        count_before = first["label_counts"].get("slow-Việc crash", 0)
        assert count_before <= 1
        await asyncio.sleep(0.5)
        second = fixture_registry.probe("taskboard@1", namespace)
        assert second["label_counts"].get("slow-Việc crash", 0) == count_before

        blocked = await env.recovery.retry_decision(env.attempt_id, fixture_reset_ok=False)
        assert blocked.allowed is False
        assert fixture_registry.reset("taskboard@1", namespace).ok
        allowed = await env.recovery.retry_decision(env.attempt_id, fixture_reset_ok=True)
        assert allowed.allowed is True
    finally:
        proc.terminate()


async def test_response_loss_after_side_effect_returns_same_receipt(
    fault_env, taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry
) -> None:
    env = fault_env
    namespace = "crash-response-loss"
    assert fixture_registry.prepare("taskboard@1", namespace).ok
    origin = f"127.0.0.1:{urlsplit(taskboard_server.base_url).port}"
    session_key = "loss-session"
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
    try:
        client = proc.client()
        client.open_session(session_key=session_key, run_id=env.run_id, attempt_id=env.attempt_id)
        login_flow(client, env, taskboard_server, namespace, session_key)
        run_command(
            client,
            env,
            session_key,
            "fill",
            {
                "target": {"intent": "new_item", "role": "textbox", "name": "Việc mới"},
                "value": literal("Việc mất phản hồi"),
            },
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

        settled = wait_for(lambda: _command_state(env, command_id) == "settled", timeout=20)
        assert settled, f"state={_command_state(env, command_id)}"
        await asyncio.sleep(0.3)
        probe = fixture_registry.probe("taskboard@1", namespace)
        assert probe["label_counts"].get("Việc mất phản hồi") == 1

        reconnected = proc.client()
        duplicate = reconnected.execute(**fields)
        assert duplicate["state"] == "settled"
        assert duplicate["outcome"] == "succeeded"
        receipt_rows = scoped_rows(
            env.worker_dsn,
            env.workspace_id,
            env.user_id,
            "SELECT count(*) FROM command_receipts WHERE command_id = %s AND state = 'settled'",
            (command_id,),
        )
        assert receipt_rows[0][0] == 1
        await asyncio.sleep(0.3)
        after = fixture_registry.probe("taskboard@1", namespace)
        assert after["label_counts"].get("Việc mất phản hồi") == 1
    finally:
        proc.terminate()


def _command_state(env, command_id: UUID) -> str | None:
    rows = scoped_rows(
        env.worker_dsn,
        env.workspace_id,
        env.user_id,
        "SELECT state FROM action_commands WHERE command_id = %s",
        (command_id,),
    )
    if not rows:
        return None
    return rows[0][0]
