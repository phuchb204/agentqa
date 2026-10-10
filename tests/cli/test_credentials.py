from __future__ import annotations

import json
from uuid import UUID

import pytest
from tests.support.postgres import seed_run

from agentqa.platform.cli import main

pytestmark = pytest.mark.asyncio


async def test_pat_never_appears_in_output_or_url(cli_env, capsys) -> None:
    runtime = cli_env["runtime"]
    run_id = await seed_run(
        runtime.engines, principal_id=cli_env["user_id"], workspace_id=UUID(cli_env["workspace_id"])
    )
    token = cli_env["token"]
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
            str(run_id),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert token not in captured.out
    assert token not in captured.err
    assert json.loads(captured.out)["run_id"] == str(run_id)


async def test_direct_token_flag_rejected(cli_env, capsys) -> None:
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
            str(cli_env["token"]),
            "--token",
            "khong-duoc-phep",
        ]
    )
    captured = capsys.readouterr()
    assert code == 64
    assert "khong-duoc-phep" not in captured.out
    assert "khong-duoc-phep" not in captured.err


async def test_custom_token_env_is_used(cli_env, monkeypatch, capsys) -> None:
    runtime = cli_env["runtime"]
    run_id = await seed_run(
        runtime.engines, principal_id=cli_env["user_id"], workspace_id=UUID(cli_env["workspace_id"])
    )
    monkeypatch.delenv("AGENTQA_TOKEN", raising=False)
    monkeypatch.setenv("AGENTQA_CLI_PAT", cli_env["token"])
    code = main(
        [
            "--base-url",
            cli_env["base_url"],
            "--token-env",
            "AGENTQA_CLI_PAT",
            "--json",
            "run",
            "get",
            "--workspace",
            cli_env["workspace_id"],
            "--run",
            str(run_id),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err


async def test_missing_token_results_in_64(cli_env, monkeypatch, capsys) -> None:
    monkeypatch.delenv("AGENTQA_TOKEN", raising=False)
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
            str(cli_env["case_revision_id"]),
        ]
    )
    captured = capsys.readouterr()
    assert code == 64
    assert json.loads(captured.out)["error"]["code"] == "input_invalid"


async def test_missing_token_env_variable_rejected(cli_env, capsys) -> None:
    code = main(
        [
            "--base-url",
            cli_env["base_url"],
            "--token-env",
            "AGENTQA_KHONG_TON_TAI",
            "--json",
            "run",
            "get",
            "--workspace",
            cli_env["workspace_id"],
            "--run",
            str(cli_env["case_revision_id"]),
        ]
    )
    captured = capsys.readouterr()
    assert code == 64
    assert "AGENTQA_KHONG_TON_TAI" in captured.out
