from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEMO_SCHEMA_VERSION = "demo-report/1"
STEP_SOURCE_TEXT = ("# Luồng tạo việc\n\nNgười dùng đăng nhập, tạo việc mới và việc xuất hiện đúng một lần.\n").encode()
AGENT_SCRIPT = {
    "go": [
        {"operation": "navigate", "intent": "open_login", "value": {"kind": "literal", "value": "/login"}},
        {"operation": "fill", "intent": "login_username", "match": {"role": "textbox", "name": "Tài khoản"}},
        {"operation": "fill", "intent": "login_password", "match": {"role": "textbox", "name": "Mật khẩu"}},
        {"operation": "click", "intent": "login_submit", "match": {"role": "button", "name": "Đăng nhập"}},
        {"operation": "fill", "intent": "new_item", "match": {"role": "textbox", "name": "Việc mới"}},
        {"operation": "click", "intent": "create_item", "match": {"role": "button", "name": "Thêm việc"}},
        {"raw": {"decision": "stop", "rationale": "script complete"}},
    ],
    "jev": [],
}
HEALING_CASE = REPO_ROOT / "benchmarks" / "public" / "cases" / "taskboard" / "healing_delete_item.yaml"
BUG_ITEM_NAME = "Việc demo bug"
BUG_DOCUMENT = {
    "schema_version": "case/1",
    "logical_key": "demo_bug_case",
    "title": "Phát hiện thiếu bản ghi thứ hai",
    "goal": "Kỳ vọng nghiệp vụ cần hai bản ghi nhưng ứng dụng chỉ tạo một",
    "requirements": ["create_item"],
    "source_defs": {
        "create_item": {
            "source_content_digest": "1b37b1a900f62fb258ea067be0549ac1521129604f18dc316566c10fefe057d0",
            "anchor": {"type": "section", "value": "create-item"},
            "quote_digest": "99030afd9733cdd28fd467f6139c23619d4846791e829a44bb789867b2ee8aa3",
            "provenance": "user",
        }
    },
    "postcondition_defs": {},
    "parameter_defs": {"item_name": {"type": "string", "required": True}},
    "fixture_refs": ["taskboard@1"],
    "nodes": [
        {
            "id": "open_login",
            "kind": "action",
            "operation": "navigate",
            "value": {"kind": "literal", "value": "/login"},
            "side_effect": "read",
        },
        {
            "id": "username",
            "kind": "action",
            "operation": "fill",
            "target": {"intent": "login_username", "role": "textbox", "name": "Tài khoản"},
            "value": {"kind": "secret", "credential_ref": "taskboard.alice.username"},
            "side_effect": "reversible",
        },
        {
            "id": "password",
            "kind": "action",
            "operation": "fill",
            "target": {"intent": "login_password", "locators": [{"kind": "label", "value": "Mật khẩu"}]},
            "value": {"kind": "secret", "credential_ref": "taskboard.alice.password"},
            "side_effect": "reversible",
        },
        {
            "id": "sign_in",
            "kind": "action",
            "operation": "click",
            "target": {"intent": "login_submit", "role": "button", "name": "Đăng nhập"},
            "side_effect": "external_write",
        },
        {
            "id": "item_name",
            "kind": "action",
            "operation": "fill",
            "target": {"intent": "new_item", "role": "textbox", "name": "Việc mới"},
            "value": {"kind": "parameter", "name": "item_name", "type": "string"},
            "side_effect": "reversible",
        },
        {
            "id": "add_item",
            "kind": "action",
            "operation": "click",
            "target": {"intent": "create_item", "role": "button", "name": "Thêm việc"},
            "side_effect": "external_write",
        },
        {
            "id": "result",
            "kind": "checkpoint",
            "assertions": [
                {
                    "id": "two_records_exist",
                    "required": True,
                    "target": {
                        "intent": "created_item_row",
                        "role": "listitem",
                        "entity_scope": {
                            "field": "text",
                            "value": {"kind": "parameter", "name": "item_name", "type": "string"},
                        },
                    },
                    "comparator": "count_equals",
                    "expected": {"kind": "literal", "value": 2},
                    "source_refs": ["create_item"],
                }
            ],
        },
    ],
    "completion": {"required_nodes": ["add_item", "result"], "required_assertions": ["two_records_exist"]},
}


class DemoError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _run_db(harness, coro):
    from tools.ui_harness.runner import _run_db as harness_run_db

    return harness_run_db(coro)


def _seed_environment(harness, *, namespace: str, seed: str, item_name: str):
    import sqlalchemy as sa

    from agentqa.contracts.canonical import digest_content
    from agentqa.platform.storage import tables
    from agentqa.platform.storage.database import create_session_factory
    from agentqa.platform.storage.roles import ROLE_API
    from agentqa.platform.storage.scope import set_scope

    seed_result = harness.seed
    application_id = uuid4()
    revision_id = uuid4()
    content = {
        "target_base_url": f"{harness.taskboard_base_url}/{namespace}",
        "fixture_ref": "taskboard@1",
        "fixture_seed": seed,
        "namespace": namespace,
        "parameters": {"item_name": item_name},
    }
    engine = harness.runtime.engines[ROLE_API]
    factory = create_session_factory(engine)

    async def insert() -> None:
        async with factory() as session, session.begin():
            await set_scope(session, principal_id=seed_result.user_id, workspace_id=seed_result.workspace_id)
            await session.execute(
                sa.insert(tables.applications).values(
                    id=application_id,
                    workspace_id=seed_result.workspace_id,
                    slug=f"app-{application_id.hex[:8]}",
                    name=f"demo-{seed}",
                )
            )
            await session.execute(
                sa.insert(tables.environment_revisions).values(
                    id=revision_id,
                    workspace_id=seed_result.workspace_id,
                    application_id=application_id,
                    revision_no=1,
                    content=content,
                    content_digest=digest_content(content),
                    lifecycle="ready",
                    author="demo",
                )
            )

    _run_db(harness, insert())
    return revision_id


def _submit_run(
    harness,
    *,
    case_revision_id,
    environment_revision_id,
    policy: str = "default",
    gate_profile: str = "strict",
):
    from sqlalchemy.ext.asyncio import create_async_engine

    from agentqa.platform.runs.service import RunService, SubmitRequest
    from agentqa.platform.storage.roles import ROLE_API

    seed = harness.seed

    async def submit():
        engine = create_async_engine(harness.dsn_by_role[ROLE_API])
        try:
            service = RunService(engine)
            outcome = await service.submit(
                SubmitRequest(
                    workspace_id=seed.workspace_id,
                    principal_id=seed.user_id,
                    actor="demo",
                    idempotency_key=uuid4().hex,
                    case_revision_ids=(case_revision_id,),
                    environment_revision_id=environment_revision_id,
                    provided_capabilities=frozenset(),
                    policy=policy,
                    gate_profile=gate_profile,
                )
            )
            return outcome.run_id
        finally:
            await engine.dispose()

    return _run_db(harness, submit())


def _compare_runs(harness, run_a, run_b):
    from sqlalchemy.ext.asyncio import create_async_engine

    from agentqa.platform.runs.read_models import RunReadModel
    from agentqa.platform.storage.roles import ROLE_API

    seed = harness.seed

    async def compare():
        engine = create_async_engine(harness.dsn_by_role[ROLE_API])
        try:
            return await RunReadModel(engine).run_comparison(
                workspace_id=seed.workspace_id, principal_id=seed.user_id, run_a=run_a, run_b=run_b
            )
        finally:
            await engine.dispose()

    return _run_db(harness, compare())


def _wait_run_state(client, workspace: str, run_id, headers, *, timeout: float = 300.0) -> dict:
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/workspaces/{workspace}/runs/{run_id}", headers=headers)
        response.raise_for_status()
        last = response.json()
        if last.get("status") in ("succeeded", "failed", "cancelled", "inconclusive", "error", "blocked"):
            return last
        time.sleep(1.0)
    raise DemoError(f"run {run_id} không kết thúc trong {timeout}s (state cuối: {last})")


def _probe_label_count(harness, run_id, label: str) -> int:
    events = harness.run_events(run_id)
    for event in reversed(events):
        if event["type"] == "fixture.probed":
            counts = event["summary"].get("probe", {}).get("label_counts", {})
            return int(counts.get(label, 0))
    return -1


def run_demo(*, build_web: bool = False) -> dict[str, Any]:
    import httpx
    import yaml
    from tests.support.healing import synthetic_profile
    from tools.ui_harness.runner import HarnessError, UiHarness

    harness = UiHarness(scenario="authoring", build_web=build_web, agent_models=True)
    script_path = harness.workspace_root / "agent-script.json"
    script_path.write_text(json.dumps(AGENT_SCRIPT, ensure_ascii=False), encoding="utf-8")
    harness.agent_script = str(script_path)
    harness.healing_profile = synthetic_profile()
    steps: list[dict[str, Any]] = []
    live_calls = 0

    def record(name: str, ok: bool, detail: str) -> None:
        steps.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            raise DemoError(f"{name}: {detail}")

    try:
        harness.start()
        seed = harness.seed
        workspace = str(seed.workspace_id)
        origin = harness.api_base_url
        with httpx.Client(base_url=origin, headers={"Origin": origin}, timeout=60.0) as client:
            login = client.post("/api/v1/auth/login", json={"username": seed.username, "password": seed.password})
            login.raise_for_status()
            headers = {"X-CSRF-Token": login.json()["csrf_token"]}

            source = client.post(
                f"/api/v1/workspaces/{workspace}/sources",
                json={"logical_key": "demo_source"},
                headers=headers,
            )
            source.raise_for_status()
            source_id = source.json()["id"]
            upload = client.post(
                f"/api/v1/workspaces/{workspace}/sources/{source_id}/revisions",
                data={"logical_key": "demo_source"},
                files={"file": ("demo-source.md", STEP_SOURCE_TEXT, "text/markdown")},
                headers=headers,
            )
            upload.raise_for_status()
            revision_no = upload.json()["revision"]["revision_no"]
            segments = upload.json().get("segments", [])
            record(
                "source.document_ingested",
                bool(segments),
                f"source={source_id} revision={revision_no} segments={len(segments)}",
            )

            job_response = client.post(
                f"/api/v1/workspaces/{workspace}/authoring-jobs",
                json={
                    "goal": "Tạo việc mới và xác nhận xuất hiện đúng một lần",
                    "url": f"{harness.taskboard_base_url}/demo",
                    "expectations": ["Việc mới xuất hiện đúng một lần trong danh sách"],
                    "requirement_keys": ["create_item"],
                    "sources": [{"source_id": source_id, "revision_no": revision_no}],
                },
                headers=headers,
            )
            job_response.raise_for_status()
            job = job_response.json()
            deadline = time.monotonic() + 60
            while not job.get("proposals") and time.monotonic() < deadline:
                time.sleep(0.2)
                job = client.get(f"/api/v1/workspaces/{workspace}/jobs/{job['job_id']}", headers=headers).json()
            proposals = job.get("proposals", [])
            record(
                "authoring.proposal_generated",
                bool(proposals),
                f"job={job['job_id']} state={job['state']} proposals={len(proposals)}",
            )
            proposal = proposals[0]

            case = client.post(
                f"/api/v1/workspaces/{workspace}/cases", json={"logical_key": "demo_case"}, headers=headers
            )
            case.raise_for_status()
            case_id = case.json()["id"]
            applied = client.post(
                f"/api/v1/workspaces/{workspace}/proposals/{proposal['proposal_id']}/apply",
                json={"case_id": case_id, "expected_edit_version": 0},
                headers={**headers, "If-Match": '"0"'},
            )
            applied.raise_for_status()
            record(
                "authoring.proposal_applied",
                applied.json()["edit_version"] >= 1,
                f"case={case_id} edit_version={applied.json()['edit_version']} diff={len(applied.json()['diff'])}",
            )

            source_names = list(applied.json()["content"].get("source_defs", {}).keys())
            confirmed = client.post(
                f"/api/v1/workspaces/{workspace}/cases/{case_id}/draft/confirm-sources",
                json={"source_names": source_names},
                headers={**headers, "If-Match": f'"{applied.json()["edit_version"]}"'},
            )
            confirmed.raise_for_status()
            promoted = client.post(
                f"/api/v1/workspaces/{workspace}/cases/{case_id}/draft/promote",
                headers={**headers, "If-Match": f'"{confirmed.json()["edit_version"]}"'},
            )
            promoted.raise_for_status()
            from uuid import UUID as _UUID

            revision_id = _UUID(promoted.json()["revision_id"])
            record(
                "case.promoted_ready",
                promoted.json()["revision_no"] >= 1,
                f"revision={revision_id} digest={promoted.json()['content_digest'][:12]}",
            )

            agent_run = _submit_run(
                harness,
                case_revision_id=revision_id,
                environment_revision_id=seed.environment_revision_id,
                policy="llm",
                gate_profile="strict",
            )
            agent_state = _wait_run_state(client, workspace, agent_run, headers)
            agent_count = _probe_label_count(harness, agent_run, "Việc UI E2E")
            record(
                "agent.run_passed",
                agent_state["verdict"] == "passed" and agent_count == 1,
                f"run={agent_run} verdict={agent_state['verdict']} item_count={agent_count} policy=llm (fake)",
            )

            replay_run = harness.run_replay(revision_id)
            replay_state = _wait_run_state(client, workspace, replay_run, headers)
            record(
                "replay.run_passed",
                replay_state["verdict"] == "passed",
                f"run={replay_run} verdict={replay_state['verdict']} gate={replay_state['gate']}",
            )

            healing_document = yaml.safe_load(HEALING_CASE.read_text(encoding="utf-8"))
            healing_document["logical_key"] = "demo_healing"
            healing_revision = harness.seed_case_document(logical_key="demo_healing", document=healing_document)
            heal_run = harness.run_replay(healing_revision, policy="replay_healing", gate_profile="allow_healing")
            heal_state = _wait_run_state(client, workspace, heal_run, headers)
            record(
                "mutation.healed",
                heal_state["verdict"] == "passed" and "healed" in heal_state["reasons"],
                f"run={heal_run} verdict={heal_state['verdict']} reasons={heal_state['reasons']}",
            )

            bug_environment = _seed_environment(harness, namespace="demo-bug", seed="success", item_name=BUG_ITEM_NAME)
            harness.healing_profile = None
            bug_revision = harness.seed_case_document(logical_key="demo_bug_case", document=dict(BUG_DOCUMENT))
            bug_run = _submit_run(
                harness,
                case_revision_id=bug_revision,
                environment_revision_id=bug_environment,
                policy="default",
                gate_profile="strict",
            )
            bug_state = _wait_run_state(client, workspace, bug_run, headers)
            bug_count = _probe_label_count(harness, bug_run, BUG_ITEM_NAME)
            bug_events = harness.run_events(bug_run)
            bug_probe: dict = {}
            bug_assertions: list = []
            for event in reversed(bug_events):
                if event["type"] == "fixture.probed":
                    bug_probe = event["summary"].get("probe", {})
                    break
            detail_response = client.get(f"/api/v1/workspaces/{workspace}/runs/{bug_run}/detail", headers=headers)
            if detail_response.status_code == 200:
                for execution in detail_response.json().get("executions", []):
                    for checkpoint in execution.get("checkpoints", []):
                        for assertion in checkpoint.get("assertions", []):
                            bug_assertions.append(
                                {
                                    "id": assertion.get("assertion_id"),
                                    "status": assertion.get("status"),
                                    "observed": str(assertion.get("observed"))[:80],
                                }
                            )
            record(
                "bug.detected",
                bug_state["verdict"] == "failed" and bug_count == 1,
                f"run={bug_run} verdict={bug_state['verdict']} observed_count={bug_count} "
                f"labels={bug_probe.get('label_counts')} assertions={bug_assertions}",
            )

            report_response = client.post(
                f"/api/v1/workspaces/{workspace}/runs/{bug_run}/reports",
                json={"format": "json"},
                headers=headers,
            )
            report_response.raise_for_status()
            report = report_response.json()
            content = client.get(
                f"/api/v1/workspaces/{workspace}/reports/{report['report_id']}/content", headers=headers
            )
            record(
                "evidence.report",
                content.status_code == 200 and bool(report.get("digest")),
                f"report={report['report_id']} digest={str(report.get('digest'))[:12]} status={content.status_code}",
            )

            comparison = _compare_runs(harness, agent_run, replay_run)
            policy_rows = [row for row in comparison.get("config_diff", []) if row["field"] == "policy"]
            policy_diff = policy_rows[0] if policy_rows else None
            record(
                "compare.config_diff",
                policy_diff is not None and policy_diff["equal"] is False,
                f"run_a={agent_run} run_b={replay_run} policy_a={policy_diff['a'] if policy_diff else None}",
            )

        ok = all(step["ok"] for step in steps)
        return {
            "schema_version": DEMO_SCHEMA_VERSION,
            "tool": "run_demo",
            "mode": "fake",
            "live_calls": live_calls,
            "ok": ok,
            "steps": steps,
            "workspace_id": workspace,
            "generated_at": _now_iso(),
        }
    except (HarnessError, DemoError) as error:
        steps.append({"name": "demo.error", "ok": False, "detail": str(error)})
        return {
            "schema_version": DEMO_SCHEMA_VERSION,
            "tool": "run_demo",
            "mode": "fake",
            "live_calls": live_calls,
            "ok": False,
            "steps": steps,
            "generated_at": _now_iso(),
        }
    finally:
        harness.stop()


__all__ = ["run_demo"]
