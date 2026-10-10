from __future__ import annotations

import json
from uuid import UUID

import pytest
import sqlalchemy as sa
from tests.support.postgres import scoped_transaction, seed_run

from agentqa.platform.cli import main
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API

pytestmark = pytest.mark.asyncio


async def test_detached_submit_returns_immediately(cli_env, capsys) -> None:
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
            cli_env["case_revision_id"],
            "--detach",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    body = json.loads(captured.out)
    assert body["detached"] is True
    run_id = body["run_id"]
    code = main(
        [
            "--base-url",
            cli_env["base_url"],
            "--json",
            "run",
            "get",
            "--workspace",
            cli_env["workspace_id"],
            "--run",
            run_id,
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out)["status"] == "queued"


async def test_ctrl_c_attached_sends_cancel_and_exits_130(cli_env, capsys) -> None:
    runtime = cli_env["runtime"]
    workspace_id = UUID(cli_env["workspace_id"])
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
            cli_env["case_revision_id"],
        ],
        interrupt_after_polls=0,
    )
    captured = capsys.readouterr()
    assert code == 130, captured.out + captured.err
    body = json.loads(captured.out)
    run_id = UUID(body["run_id"])
    assert body["status"] == "cancel_requested"
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=cli_env["user_id"], workspace_id=workspace_id
    ) as session:
        controls = (
            await session.execute(
                sa.select(tables.run_controls.c.action, tables.run_controls.c.reason).where(
                    tables.run_controls.c.run_id == run_id
                )
            )
        ).all()
    assert [(row.action, row.reason) for row in controls] == [("cancel", "cli-interrupt")]


async def test_cancel_command_sends_control(cli_env) -> None:
    runtime = cli_env["runtime"]
    workspace_id = UUID(cli_env["workspace_id"])
    run_id = await seed_run(runtime.engines, principal_id=cli_env["user_id"], workspace_id=workspace_id)
    code = main(
        [
            "--base-url",
            cli_env["base_url"],
            "--json",
            "run",
            "cancel",
            "--workspace",
            cli_env["workspace_id"],
            "--run",
            str(run_id),
            "--reason",
            "operator",
        ]
    )
    assert code == 0
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=cli_env["user_id"], workspace_id=workspace_id
    ) as session:
        count = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(tables.run_controls)
                .where(tables.run_controls.c.run_id == run_id, tables.run_controls.c.action == "cancel")
            )
        ).scalar_one()
    assert count == 1
