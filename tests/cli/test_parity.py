from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tests.support.platform import service_suite_revision, suite_content

from agentqa.platform.cli import _build_managed_app, build_parser, main

pytestmark = pytest.mark.asyncio


async def test_managed_local_start_reuses_api_application(test_db, tmp_path: Path) -> None:
    from agentqa.platform.api.application import create_application
    from agentqa.platform.storage.roles import ROLE_API

    args = build_parser().parse_args(
        ["serve", "--dsn", test_db.dsn(ROLE_API), "--artifact-dir", str(tmp_path / "store")]
    )
    app = _build_managed_app(args)
    assert app.state.runtime is not None
    reference = create_application()

    def paths(application) -> set[str]:
        return {route.path for route in application.routes if getattr(route, "path", None) is not None}

    assert paths(app) == paths(reference)


CASE_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "valid_case_minimal.yaml"


async def test_config_validate_offline_valid(capsys, tmp_path: Path) -> None:
    target = tmp_path / "case.yaml"
    shutil.copyfile(CASE_FIXTURE, target)
    code = main(["--json", "config", "validate", "--file", str(target)])
    captured = capsys.readouterr()
    assert code == 0
    body = json.loads(captured.out)
    assert body["valid"] is True
    assert body["logical_key"] == "start_flow"
    assert len(body["content_digest"]) == 64


async def test_config_validate_offline_invalid(capsys, tmp_path: Path) -> None:
    target = tmp_path / "broken.yaml"
    target.write_text("schema_version: case/1\nlogical_key: broken\n", encoding="utf-8")
    code = main(["--json", "config", "validate", "--file", str(target)])
    captured = capsys.readouterr()
    assert code == 64
    body = json.loads(captured.out)
    assert body["error"]["code"] == "input_invalid"


async def test_export_import_roundtrip_through_cli(cli_env, capsys, tmp_path: Path) -> None:
    out = tmp_path / "bundle.yaml"
    code = main(
        [
            "--base-url",
            cli_env["base_url"],
            "--json",
            "export",
            "--workspace",
            cli_env["workspace_id"],
            "--kinds",
            "case",
            "--out",
            str(out),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    exported = json.loads(captured.out)
    assert out.is_file()
    assert len(exported["digest"]) == 64

    code = main(
        [
            "--base-url",
            cli_env["base_url"],
            "--json",
            "import",
            "--workspace",
            cli_env["workspace_id"],
            "--file",
            str(out),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    imported = json.loads(captured.out)
    assert imported["imported"]
    assert all(item["revision_no"] >= 1 for item in imported["imported"])


async def test_suite_submit_detached_and_query(cli_env, capsys) -> None:
    from uuid import UUID

    runtime = cli_env["runtime"]
    suite = await service_suite_revision(
        runtime,
        workspace_id=UUID(cli_env["workspace_id"]),
        principal_id=cli_env["user_id"],
        actor=cli_env["username"],
        logical_key="cli_suite",
        content=suite_content(
            "cli_suite",
            case_refs=[{"logical_key": "cli_case", "revision_no": 1}],
        ),
    )
    code = main(
        [
            "--base-url",
            cli_env["base_url"],
            "--json",
            "suite",
            "submit",
            "--workspace",
            cli_env["workspace_id"],
            "--suite-revision",
            str(suite.revision_id),
            "--detach",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    submitted = json.loads(captured.out)
    run_id = submitted["run_id"]

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
    assert code == 0, captured.out + captured.err
    state = json.loads(captured.out)
    assert state["status"] == "queued"
    assert len(state["executions"]) == 1
    assert state["snapshot_digest"]
