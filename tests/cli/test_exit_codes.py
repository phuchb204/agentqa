from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from tests.support.postgres import scoped_transaction

from agentqa.platform.cli import main
from agentqa.platform.runs.service import SubmitRequest
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API

pytestmark = pytest.mark.asyncio


async def _terminal_run(
    cli_env,
    *,
    run_status: str,
    verdict: str,
    gate: str | None,
    exec_status: str,
    exec_verdict: str | None,
) -> str:
    runtime = cli_env["runtime"]
    workspace_id = UUID(cli_env["workspace_id"])
    outcome = await runtime.runs.submit(
        SubmitRequest(
            workspace_id=workspace_id,
            principal_id=cli_env["user_id"],
            actor=cli_env["username"],
            idempotency_key=uuid4().hex,
            case_revision_ids=(UUID(cli_env["case_revision_id"]),),
        )
    )
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=cli_env["user_id"], workspace_id=workspace_id
    ) as session:
        await session.execute(
            sa.update(tables.executions)
            .where(tables.executions.c.run_id == outcome.run_id)
            .values(status=exec_status, verdict=exec_verdict)
        )
        await session.execute(
            sa.update(tables.runs)
            .where(tables.runs.c.id == outcome.run_id)
            .values(status=run_status, verdict=verdict, gate=gate, finalized_at=sa.func.now())
        )
    return str(outcome.run_id)


async def _result_code(cli_env, run_id: str) -> int:
    return main(
        [
            "--base-url",
            cli_env["base_url"],
            "--json",
            "run",
            "result",
            "--workspace",
            cli_env["workspace_id"],
            "--run",
            run_id,
        ]
    )


async def test_exit_code_zero_for_passed_run(cli_env, capsys) -> None:
    run_id = await _terminal_run(
        cli_env, run_status="succeeded", verdict="passed", gate="passed", exec_status="succeeded", exec_verdict="passed"
    )
    code = await _result_code(cli_env, run_id)
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err


async def test_exit_code_one_for_business_failure(cli_env, capsys) -> None:
    run_id = await _terminal_run(
        cli_env, run_status="failed", verdict="failed", gate="passed", exec_status="failed", exec_verdict="failed"
    )
    code = await _result_code(cli_env, run_id)
    assert code == 1


async def test_exit_code_two_for_inconclusive_or_gate_rejection(cli_env) -> None:
    inconclusive = await _terminal_run(
        cli_env,
        run_status="error",
        verdict="inconclusive",
        gate="error",
        exec_status="error",
        exec_verdict="inconclusive",
    )
    assert await _result_code(cli_env, inconclusive) == 2
    refused = await _terminal_run(
        cli_env,
        run_status="succeeded",
        verdict="passed",
        gate="refused",
        exec_status="succeeded",
        exec_verdict="passed",
    )
    assert await _result_code(cli_env, refused) == 2


async def test_exit_code_130_for_cancelled(cli_env) -> None:
    run_id = await _terminal_run(
        cli_env,
        run_status="cancelled",
        verdict="inconclusive",
        gate=None,
        exec_status="cancelled",
        exec_verdict=None,
    )
    assert await _result_code(cli_env, run_id) == 130


async def test_exit_code_64_for_invalid_input_and_unreachable_server(cli_env, capsys) -> None:
    code = main(["run", "get", "--workspace", cli_env["workspace_id"]])
    assert code == 64
    code = main(
        [
            "--base-url",
            "http://127.0.0.1:1",
            "--json",
            "run",
            "get",
            "--workspace",
            cli_env["workspace_id"],
            "--run",
            str(uuid4()),
        ]
    )
    captured = capsys.readouterr()
    assert code == 64
    assert json.loads(captured.out)["error"]["code"] == "input_invalid"


async def test_exit_code_64_for_blocked_submit(cli_env, capsys) -> None:
    code = main(
        [
            "--base-url",
            cli_env["base_url"],
            "--json",
            "run",
            "submit",
            "--workspace",
            cli_env["workspace_id"],
            "--case-revision",
            str(uuid4()),
            "--detach",
        ]
    )
    captured = capsys.readouterr()
    assert code == 64
    body = json.loads(captured.out)
    assert body["blocked"] is True
    assert body["blocked_reasons"]


async def test_wait_path_returns_same_code(cli_env) -> None:
    run_id = await _terminal_run(
        cli_env, run_status="failed", verdict="failed", gate="passed", exec_status="failed", exec_verdict="failed"
    )
    code = main(
        [
            "--base-url",
            cli_env["base_url"],
            "--json",
            "run",
            "wait",
            "--workspace",
            cli_env["workspace_id"],
            "--run",
            run_id,
        ]
    )
    assert code == 1
