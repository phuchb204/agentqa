from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, NoReturn
from uuid import uuid4

import httpx

from agentqa.contracts.compiler import compile_case_document
from agentqa.contracts.errors import AgentQAValidationError

EXIT_OK = 0
EXIT_BUSINESS_FAILED = 1
EXIT_NON_BUSINESS = 2
EXIT_INVALID = 64
EXIT_CANCELLED = 130

DEFAULT_TIMEOUT_SECONDS = 600.0
CANCEL_WAIT_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.5
TOKEN_ENV_DEFAULT = "AGENTQA_TOKEN"


class CliInputError(Exception):
    def __init__(self, message: str, *, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload
        super().__init__(message)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        if "unrecognized arguments" in message:
            message = "Tham số không hợp lệ (không nhận token trực tiếp trên dòng lệnh)"
        raise CliInputError(message)


def _fail(code: str, message: str, *, as_json: bool, payload: dict[str, Any] | None = None) -> None:
    if as_json:
        body: dict[str, Any] = {"error": {"code": code, "message": message}}
        if payload:
            body.update(payload)
        print(json.dumps(body, ensure_ascii=False, sort_keys=True, default=str))
    else:
        print(f"Lỗi: {message}", file=sys.stderr)
        if payload and payload.get("blocked_reasons"):
            print(f"  Lý do: {', '.join(payload['blocked_reasons'])}", file=sys.stderr)


def _emit(payload: dict[str, Any], *, as_json: bool, human: str) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    else:
        print(human)


def _resolve_token(token_env: str | None) -> str | None:
    if token_env:
        value = os.environ.get(token_env)
        if not value:
            raise CliInputError(f"Biến môi trường '{token_env}' không chứa token")
        return value
    return os.environ.get(TOKEN_ENV_DEFAULT)


def _build_client(base_url: str, token: str | None) -> httpx.Client:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=30.0)


def _request(
    client: httpx.Client, method: str, path: str, *, json_body: dict | None = None, headers: dict | None = None
) -> httpx.Response:
    try:
        return client.request(method, path, json=json_body, headers=headers)
    except httpx.HTTPError as error:
        raise CliInputError(f"Không kết nối được API: {type(error).__name__}") from error


def _expect(response: httpx.Response) -> dict[str, Any]:
    if response.status_code >= 400:
        try:
            body = response.json()
            message = str(body.get("message") or body.get("code") or response.status_code)
        except ValueError:
            message = str(response.status_code)
        raise CliInputError(f"API trả {response.status_code}: {message}")
    if not response.content:
        return {}
    return response.json()


def _exit_for_result(result: dict[str, Any]) -> int:
    if result.get("status") == "cancelled":
        return EXIT_CANCELLED
    executions = result.get("executions") or []
    gate = result.get("gate")
    if gate in ("refused", "error"):
        return EXIT_NON_BUSINESS
    if any(execution.get("status") in ("error", "blocked", "inconclusive") for execution in executions):
        return EXIT_NON_BUSINESS
    if result.get("verdict") == "failed" or any(execution.get("verdict") == "failed" for execution in executions):
        return EXIT_BUSINESS_FAILED
    if (
        executions
        and all(execution.get("status") == "succeeded" for execution in executions)
        and result.get("verdict") == "passed"
        and gate in ("passed", None)
    ):
        return EXIT_OK
    return EXIT_NON_BUSINESS


def _wait_for_result(
    client: httpx.Client,
    *,
    workspace: str,
    run_id: str,
    timeout: float,
    interrupt_after_polls: int | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    polls = 0
    while True:
        if interrupt_after_polls is not None and polls == interrupt_after_polls:
            raise KeyboardInterrupt()
        polls += 1
        response = _request(client, "GET", f"/api/v1/workspaces/{workspace}/runs/{run_id}/result")
        if response.status_code == 409:
            if time.monotonic() > deadline:
                raise CliInputError("Hết thời gian chờ lượt chạy terminal")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        return _expect(response)


def _request_cancel(client: httpx.Client, *, workspace: str, run_id: str, reason: str) -> None:
    response = _request(
        client,
        "POST",
        f"/api/v1/workspaces/{workspace}/runs/{run_id}/controls",
        json_body={"action": "cancel", "reason": reason},
        headers={"Idempotency-Key": uuid4().hex},
    )
    _expect(response)


def _command_config_validate(args: argparse.Namespace, *, as_json: bool) -> int:
    path = Path(args.file)
    if not path.is_file():
        raise CliInputError(f"Không tìm thấy file '{args.file}'")
    text = path.read_text(encoding="utf-8")
    try:
        compiled = compile_case_document(text)
    except AgentQAValidationError as error:
        detail = "; ".join(f"{'.'.join(str(part) for part in item.path)}: {item.message}" for item in error.errors)
        _fail("input_invalid", detail or "Case không hợp lệ", as_json=as_json)
        return EXIT_INVALID
    _emit(
        {"valid": True, "logical_key": compiled.case.logical_key, "content_digest": compiled.content_digest},
        as_json=as_json,
        human=f"Hợp lệ: {compiled.case.logical_key} · digest {compiled.content_digest[:12]}…",
    )
    return EXIT_OK


def _command_export(args: argparse.Namespace, client: httpx.Client, *, as_json: bool) -> int:
    payload: dict[str, Any] = {"format": args.format}
    if args.kinds:
        payload["kinds"] = [item.strip() for item in args.kinds.split(",") if item.strip()]
    body = _expect(_request(client, "POST", f"/api/v1/workspaces/{args.workspace}/exports", json_body=payload))
    out = Path(args.out)
    out.write_text(str(body.get("content", "")), encoding="utf-8")
    _emit(
        {"digest": body.get("digest"), "format": body.get("format"), "path": str(out)},
        as_json=as_json,
        human=f"Đã export {body.get('format')} vào {out} · digest {str(body.get('digest'))[:12]}…",
    )
    return EXIT_OK


def _command_import(args: argparse.Namespace, client: httpx.Client, *, as_json: bool) -> int:
    path = Path(args.file)
    if not path.is_file():
        raise CliInputError(f"Không tìm thấy file '{args.file}'")
    fmt = args.format
    if fmt == "auto":
        fmt = "json" if path.suffix.lower() == ".json" else "yaml"
    body = _expect(
        _request(
            client,
            "POST",
            f"/api/v1/workspaces/{args.workspace}/imports",
            json_body={"format": fmt, "content": path.read_text(encoding="utf-8")},
        )
    )
    imported = body.get("imported", [])
    _emit(
        {"imported": imported},
        as_json=as_json,
        human=f"Đã import {len(imported)} revision",
    )
    return EXIT_OK


def _submit_run(args: argparse.Namespace, client: httpx.Client) -> str:
    case_revisions = getattr(args, "case_revision", None) or []
    suite_revision = getattr(args, "suite_revision", None)
    if bool(case_revisions) == bool(suite_revision):
        raise CliInputError("Cần đúng một trong --case-revision (có thể lặp) hoặc --suite-revision")
    payload: dict[str, Any] = {
        "case_revision_ids": case_revisions,
        "suite_revision_id": suite_revision,
        "policy": args.policy,
        "gate_profile": args.gate_profile,
    }
    if args.environment:
        payload["environment_revision_id"] = args.environment
    idempotency_key = args.idempotency_key or uuid4().hex
    body = _expect(
        _request(
            client,
            "POST",
            f"/api/v1/workspaces/{args.workspace}/runs",
            json_body=payload,
            headers={"Idempotency-Key": idempotency_key},
        )
    )
    if body.get("blocked"):
        raise CliInputError(
            "Submit bị chặn do input không hợp lệ",
            payload={
                "run_id": body.get("run_id"),
                "blocked": True,
                "blocked_reasons": body.get("blocked_reasons", []),
            },
        )
    return str(body.get("run_id"))


def _command_submit(args: argparse.Namespace, client: httpx.Client) -> int:
    as_json = args.json_output
    run_id = _submit_run(args, client)
    if args.detach:
        _emit({"run_id": run_id, "detached": True}, as_json=as_json, human=f"Đã submit (detached): {run_id}")
        return EXIT_OK
    return _wait_attached(args, client, run_id)


def _wait_attached(args: argparse.Namespace, client: httpx.Client, run_id: str) -> int:
    as_json = args.json_output
    try:
        result = _wait_for_result(
            client,
            workspace=args.workspace,
            run_id=run_id,
            timeout=args.timeout,
            interrupt_after_polls=getattr(args, "interrupt_after_polls", None),
        )
    except KeyboardInterrupt:
        _request_cancel(client, workspace=args.workspace, run_id=run_id, reason="cli-interrupt")
        try:
            result = _wait_for_result(client, workspace=args.workspace, run_id=run_id, timeout=CANCEL_WAIT_SECONDS)
        except (CliInputError, KeyboardInterrupt):
            _emit(
                {"run_id": run_id, "status": "cancel_requested"}, as_json=as_json, human=f"{run_id}: cancel_requested"
            )
            return EXIT_CANCELLED
        _emit(result, as_json=as_json, human=f"{run_id}: {result.get('status')} · verdict {result.get('verdict')}")
        return EXIT_CANCELLED
    _emit(result, as_json=as_json, human=f"{run_id}: {result.get('status')} · verdict {result.get('verdict')}")
    return _exit_for_result(result)


def _command_run_get(args: argparse.Namespace, client: httpx.Client) -> int:
    body = _expect(_request(client, "GET", f"/api/v1/workspaces/{args.workspace}/runs/{args.run}"))
    _emit(
        body,
        as_json=args.json_output,
        human=f"{args.run}: {body.get('status')} · verdict {body.get('verdict')} · gate {body.get('gate')}",
    )
    return EXIT_OK


def _command_run_result(args: argparse.Namespace, client: httpx.Client) -> int:
    response = _request(client, "GET", f"/api/v1/workspaces/{args.workspace}/runs/{args.run}/result")
    if response.status_code == 409:
        _fail("not_terminal", "Lượt chạy chưa terminal", as_json=args.json_output)
        return EXIT_NON_BUSINESS
    result = _expect(response)
    _emit(
        result,
        as_json=args.json_output,
        human=f"{args.run}: {result.get('status')} · verdict {result.get('verdict')} · gate {result.get('gate')}",
    )
    return _exit_for_result(result)


def _command_run_wait(args: argparse.Namespace, client: httpx.Client) -> int:
    try:
        result = _wait_for_result(
            client,
            workspace=args.workspace,
            run_id=args.run,
            timeout=args.timeout,
            interrupt_after_polls=getattr(args, "interrupt_after_polls", None),
        )
    except KeyboardInterrupt:
        _request_cancel(client, workspace=args.workspace, run_id=args.run, reason="cli-interrupt")
        return EXIT_CANCELLED
    _emit(
        result, as_json=args.json_output, human=f"{args.run}: {result.get('status')} · verdict {result.get('verdict')}"
    )
    return _exit_for_result(result)


def _command_run_cancel(args: argparse.Namespace, client: httpx.Client) -> int:
    _request_cancel(client, workspace=args.workspace, run_id=args.run, reason=args.reason)
    _emit({"run_id": args.run, "cancel_requested": True}, as_json=args.json_output, human="Đã gửi yêu cầu huỷ")
    if args.wait_effective:
        result = _wait_for_result(client, workspace=args.workspace, run_id=args.run, timeout=args.timeout)
        _emit(result, as_json=args.json_output, human=f"{args.run}: {result.get('status')}")
        return _exit_for_result(result)
    return EXIT_OK


def _command_calibration_validate(args: argparse.Namespace, *, as_json: bool) -> int:
    from agentqa.platform.calibration import load_manifest
    from agentqa.platform.calibration.service import CalibrationService

    path = Path(args.manifest)
    if not path.is_file():
        raise CliInputError(f"Không tìm thấy manifest '{args.manifest}'")
    try:
        manifest = load_manifest(path)
    except Exception as error:
        _fail("input_invalid", f"Manifest không hợp lệ: {type(error).__name__}", as_json=as_json)
        return EXIT_INVALID
    service = CalibrationService(manifest, receipt_dir=Path(args.receipt_dir) if args.receipt_dir else None)
    payload = service.validate()
    _emit(
        payload,
        as_json=as_json,
        human=f"Hợp lệ: {payload['profile_id']}@{payload['version']} · digest {payload['manifest_digest'][:12]}…",
    )
    return EXIT_OK


def _command_calibration_status(args: argparse.Namespace, *, as_json: bool) -> int:
    from agentqa.platform.calibration import load_manifest
    from agentqa.platform.calibration.service import CalibrationService

    path = Path(args.manifest)
    if not path.is_file():
        raise CliInputError(f"Không tìm thấy manifest '{args.manifest}'")
    manifest = load_manifest(path)
    service = CalibrationService(manifest, receipt_dir=Path(args.receipt_dir) if args.receipt_dir else None)
    payload = service.status()
    _emit(
        payload,
        as_json=as_json,
        human=f"{payload['profile_id']}@{payload['version']}: {payload['status']} ({payload.get('reason')})",
    )
    return EXIT_OK


def _require_model_pair(manifest_pair: str) -> None:
    import os

    active = os.environ.get("AGENTQA_MODEL_PAIR", "opencode")
    if active != manifest_pair:
        raise CliInputError(
            f"Manifest pin pair '{manifest_pair}' nhưng worker đang dùng '{active}' "
            "(đặt AGENTQA_MODEL_PAIR cho khớp, không tự đổi pair khi chạy)"
        )


def _command_calibration_execute(args: argparse.Namespace, *, as_json: bool) -> int:
    import time

    from agentqa.platform.calibration import load_manifest
    from agentqa.platform.calibration.live import (
        LiveResearchHarness,
        load_private_oracle,
        research_ref_resolver,
        run_live_calibration,
        start_benchmark_apps,
        stop_benchmark_apps,
    )
    from agentqa.platform.calibration.service import CalibrationService

    if not args.live:
        _fail(
            "input_invalid",
            "Calibration execute chỉ chạy với --live (offline dùng validate/status)",
            as_json=as_json,
        )
        return EXIT_INVALID
    path = Path(args.manifest)
    if not path.is_file():
        raise CliInputError(f"Không tìm thấy manifest '{args.manifest}'")
    manifest = load_manifest(path)
    _require_model_pair(manifest.budgets.model_pair)
    oracle_module = load_private_oracle()
    apps = start_benchmark_apps()
    root = Path("artifacts") / "research" / f"calibration-{manifest.profile_id}-{int(time.time())}"
    harness = LiveResearchHarness(apps=apps, root=root, ref_resolver=research_ref_resolver(oracle_module))
    try:
        harness.start()
        outcome = run_live_calibration(manifest, harness, oracle_module, candidate_limit=args.candidates)
    finally:
        harness.stop()
        stop_benchmark_apps(apps)
    receipt = outcome["receipt"]
    root.mkdir(parents=True, exist_ok=True)
    (root / "trials.json").write_text(
        json.dumps(outcome["trials"], ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    service = CalibrationService(manifest, receipt_dir=Path(args.receipt_dir) if args.receipt_dir else None)
    service.save_receipt(receipt)
    payload = {
        "profile_id": receipt.profile_id,
        "status": receipt.status,
        "reason": receipt.reason,
        "evidence": receipt.evidence,
        "sample_units": receipt.sample_units,
        "groups": receipt.groups,
        "bound_upper": receipt.bound_upper,
        "refusal_coverage": receipt.refusal_coverage,
        "winner": outcome["winner"],
        "calls_used": outcome["calls_used"],
        "skipped": outcome["skipped"],
        "artifacts_dir": str(root),
        "receipt_path": str(service.receipt_path()),
    }
    _emit(
        payload,
        as_json=as_json,
        human=f"{receipt.profile_id}@{receipt.version}: {receipt.status} ({receipt.reason}) · "
        f"units {receipt.sample_units} · bound {receipt.bound_upper} · calls {outcome['calls_used']}",
    )
    return EXIT_OK


def _command_experiment_validate(args: argparse.Namespace, *, as_json: bool) -> int:
    import yaml

    from agentqa.platform.experiments import ExperimentManifest, validate_manifest

    path = Path(args.manifest)
    if not path.is_file():
        raise CliInputError(f"Không tìm thấy manifest '{args.manifest}'")
    try:
        manifest = ExperimentManifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except Exception as error:
        _fail("input_invalid", f"Manifest không hợp lệ: {type(error).__name__}", as_json=as_json)
        return EXIT_INVALID
    incompatibilities = [item.model_dump() for item in validate_manifest(manifest)]
    blocking = [item for item in incompatibilities if item["blocking"]]
    payload = {
        "experiment_id": manifest.experiment_id,
        "version": manifest.version,
        "manifest_digest": manifest.digest(),
        "incompatibilities": incompatibilities,
    }
    _emit(
        payload,
        as_json=as_json,
        human=f"{manifest.experiment_id}@{manifest.version}: {len(blocking)} blocking, "
        f"{len(incompatibilities) - len(blocking)} warning",
    )
    return EXIT_INVALID if blocking else EXIT_OK


def _command_experiment_execute(args: argparse.Namespace, *, as_json: bool) -> int:
    import time

    import yaml

    from agentqa.platform.calibration.live import (
        LiveResearchHarness,
        load_private_oracle,
        research_ref_resolver,
        start_benchmark_apps,
        stop_benchmark_apps,
    )
    from agentqa.platform.experiments import ExperimentManifest
    from agentqa.platform.experiments.live import run_live_experiment

    if not args.live:
        _fail(
            "input_invalid",
            "Experiment execute chỉ chạy với --live (offline dùng validate/recompute)",
            as_json=as_json,
        )
        return EXIT_INVALID
    path = Path(args.manifest)
    if not path.is_file():
        raise CliInputError(f"Không tìm thấy manifest '{args.manifest}'")
    manifest = ExperimentManifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    _require_model_pair(manifest.budgets.model_pair)
    oracle_module = load_private_oracle()
    apps = start_benchmark_apps()
    root = Path("artifacts") / "research" / f"harness-{manifest.experiment_id}-{int(time.time())}"
    harness = LiveResearchHarness(apps=apps, root=root, ref_resolver=research_ref_resolver(oracle_module))
    try:
        harness.start()
        outcome = run_live_experiment(manifest, harness, oracle_module, slot_limit=args.slots)
    finally:
        harness.stop()
        stop_benchmark_apps(apps)
    arms_summary = {
        arm_id: {
            "oracle_lower": metrics["oracle"]["success_lower_bound"],
            "oracle_upper": metrics["oracle"]["success_upper_bound"],
            "unscorable": metrics["oracle"]["unscorable"],
            "false_passes": metrics["false_passes"],
            "false_heals": metrics["healing"]["false_heals"],
            "blocked": metrics["blocked"],
            "errors": metrics["errors"],
            "completed": metrics["completed"],
        }
        for arm_id, metrics in outcome["analysis"]["arms"].items()
    }
    payload = {
        "experiment_id": manifest.experiment_id,
        "revision_id": outcome["revision_id"],
        "summary": outcome["summary"],
        "calls_used": outcome["calls_used"],
        "image_capability_verified": outcome["image_capability_verified"],
        "blocked_slots": len(outcome["blocked"]),
        "arms": arms_summary,
        "bundle_dir": outcome["bundle_dir"],
    }
    _emit(
        payload,
        as_json=as_json,
        human=f"{manifest.experiment_id}: {outcome['summary']} · calls {outcome['calls_used']} · "
        f"blocked {len(outcome['blocked'])} · bundle {outcome['bundle_dir']}",
    )
    return EXIT_OK


def _command_experiment_recompute(args: argparse.Namespace, *, as_json: bool) -> int:
    from agentqa.platform.experiments import recompute

    bundle = Path(args.bundle)
    if not bundle.is_dir():
        raise CliInputError(f"Không tìm thấy bundle '{args.bundle}'")
    report = recompute(bundle)
    payload = {"matches": report["matches"], "diffs": report["diffs"], "charts": report["charts"]}
    _emit(
        payload,
        as_json=as_json,
        human=("Recompute khớp bundle" if report["matches"] else f"Recompute lệch: {report['diffs']}"),
    )
    return EXIT_OK if report["matches"] else EXIT_NON_BUSINESS


def _command_suite_bind(args: argparse.Namespace, client: httpx.Client) -> int:
    body = _expect(
        _request(
            client,
            "POST",
            f"/api/v1/workspaces/{args.workspace}/suites/{args.suite}/revisions/{args.revision}/bind",
        )
    )
    _emit(
        body,
        as_json=args.json_output,
        human=f"Bind: {len(body.get('executions', []))} execution dự kiến · facts {body.get('facts', [])}",
    )
    return EXIT_OK


def _build_managed_app(args: argparse.Namespace) -> Any:
    from agentqa.platform.api.application import create_application
    from agentqa.platform.api.runtime import PlatformRuntime, RuntimeProfile
    from agentqa.platform.artifacts.store import FileSystemBlobStore
    from agentqa.platform.storage.roles import ROLE_API, ROLE_WORKER

    dsn = args.dsn or os.environ.get("AGENTQA_DSN")
    if not dsn:
        raise CliInputError("Cần --dsn hoặc AGENTQA_DSN cho managed local start")
    dsn_by_role = {ROLE_API: dsn}
    worker_dsn = args.worker_dsn or os.environ.get("AGENTQA_WORKER_DSN")
    if worker_dsn:
        dsn_by_role[ROLE_WORKER] = worker_dsn
    shared_origins = [item.strip() for item in (args.shared_origin or []) if item.strip()]
    profile = RuntimeProfile.shared(frozenset(shared_origins)) if shared_origins else RuntimeProfile.local()
    runtime = PlatformRuntime.build(
        profile=profile,
        dsn_by_role=dsn_by_role,
        artifact_store=FileSystemBlobStore(Path(args.artifact_dir)),
    )
    return create_application(runtime)


def _command_serve(args: argparse.Namespace) -> int:
    import uvicorn

    app = _build_managed_app(args)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return EXIT_OK


def _add_workspace(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", required=True, help="Workspace ID")


def _add_submit_options(parser: argparse.ArgumentParser, *, suite: bool) -> None:
    if suite:
        parser.add_argument("--suite-revision", required=True, help="Suite revision ID")
    else:
        parser.add_argument("--case-revision", action="append", help="Case revision ID (có thể lặp)")
        parser.add_argument("--suite-revision", help="Suite revision ID (thay cho case)")
    parser.add_argument("--environment", help="Environment revision ID")
    parser.add_argument("--policy", default="default")
    parser.add_argument("--gate-profile", default="default")
    parser.add_argument("--idempotency-key", help="Idempotency-Key tường minh")
    parser.add_argument("--detach", action="store_true", help="Không chờ terminal")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="agentqa", description="AgentQA CLI (HTTP client, dùng chung API services)")
    parser.add_argument("--base-url", default=os.environ.get("AGENTQA_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--token-env", default=None, help=f"Tên env var chứa PAT (mặc định {TOKEN_ENV_DEFAULT})")
    parser.add_argument("--json", dest="json_output", action="store_true", help="Stdout JSON cho automation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    config = subparsers.add_parser("config", help="Kiểm tra cấu hình")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    validate = config_sub.add_parser("validate", help="Validate case YAML offline")
    validate.add_argument("--file", required=True)
    validate.set_defaults(handler="config-validate")

    export = subparsers.add_parser("export", help="Export workspace bundle")
    _add_workspace(export)
    export.add_argument("--out", required=True)
    export.add_argument("--kinds", help="Danh sách kind, phân tách bằng dấu phẩy")
    export.add_argument("--format", choices=["yaml", "json"], default="yaml")
    export.set_defaults(handler="export")

    import_cmd = subparsers.add_parser("import", help="Import bundle")
    _add_workspace(import_cmd)
    import_cmd.add_argument("--file", required=True)
    import_cmd.add_argument("--format", choices=["yaml", "json", "auto"], default="auto")
    import_cmd.set_defaults(handler="import")

    run = subparsers.add_parser("run", help="Submit/query/cancel lượt chạy")
    run_sub = run.add_subparsers(dest="run_command", required=True)
    run_submit = run_sub.add_parser("submit")
    _add_workspace(run_submit)
    _add_submit_options(run_submit, suite=False)
    run_submit.set_defaults(handler="run-submit")
    run_get = run_sub.add_parser("get")
    _add_workspace(run_get)
    run_get.add_argument("--run", required=True)
    run_get.set_defaults(handler="run-get")
    run_result = run_sub.add_parser("result")
    _add_workspace(run_result)
    run_result.add_argument("--run", required=True)
    run_result.set_defaults(handler="run-result")
    run_wait = run_sub.add_parser("wait")
    _add_workspace(run_wait)
    run_wait.add_argument("--run", required=True)
    run_wait.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    run_wait.set_defaults(handler="run-wait")
    run_cancel = run_sub.add_parser("cancel")
    _add_workspace(run_cancel)
    run_cancel.add_argument("--run", required=True)
    run_cancel.add_argument("--reason", default="cli-cancel")
    run_cancel.add_argument("--wait-effective", action="store_true")
    run_cancel.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    run_cancel.set_defaults(handler="run-cancel")

    suite = subparsers.add_parser("suite", help="Thao tác suite")
    suite_sub = suite.add_subparsers(dest="suite_command", required=True)
    suite_submit = suite_sub.add_parser("submit")
    _add_workspace(suite_submit)
    _add_submit_options(suite_submit, suite=True)
    suite_submit.set_defaults(handler="suite-submit")
    suite_bind = suite_sub.add_parser("bind")
    _add_workspace(suite_bind)
    suite_bind.add_argument("--suite", required=True)
    suite_bind.add_argument("--revision", required=True)
    suite_bind.set_defaults(handler="suite-bind")

    calibration = subparsers.add_parser("calibration", help="Calibration manifest (offline validate/status)")
    calibration_sub = calibration.add_subparsers(dest="calibration_command", required=True)
    calibration_validate = calibration_sub.add_parser("validate")
    calibration_validate.add_argument("--manifest", required=True)
    calibration_validate.add_argument("--receipt-dir", default=None)
    calibration_validate.set_defaults(handler="calibration-validate")
    calibration_status = calibration_sub.add_parser("status")
    calibration_status.add_argument("--manifest", required=True)
    calibration_status.add_argument("--receipt-dir", default=None)
    calibration_status.set_defaults(handler="calibration-status")
    calibration_execute = calibration_sub.add_parser("execute")
    calibration_execute.add_argument("--manifest", required=True)
    calibration_execute.add_argument("--receipt-dir", default=None)
    calibration_execute.add_argument("--candidates", type=int, default=None)
    calibration_execute.add_argument("--live", action="store_true")
    calibration_execute.set_defaults(handler="calibration-execute")

    experiment = subparsers.add_parser("experiment", help="Experiment manifest (offline validate/recompute)")
    experiment_sub = experiment.add_subparsers(dest="experiment_command", required=True)
    experiment_validate = experiment_sub.add_parser("validate")
    experiment_validate.add_argument("--manifest", required=True)
    experiment_validate.set_defaults(handler="experiment-validate")
    experiment_execute = experiment_sub.add_parser("execute")
    experiment_execute.add_argument("--manifest", required=True)
    experiment_execute.add_argument("--slots", type=int, default=None)
    experiment_execute.add_argument("--live", action="store_true")
    experiment_execute.set_defaults(handler="experiment-execute")
    experiment_recompute = experiment_sub.add_parser("recompute")
    experiment_recompute.add_argument("--bundle", required=True)
    experiment_recompute.set_defaults(handler="experiment-recompute")

    serve = subparsers.add_parser("serve", help="Managed local start (cùng API services)")
    serve.add_argument("--dsn", help="DSN PostgreSQL (hoặc AGENTQA_DSN)")
    serve.add_argument("--worker-dsn", help="DSN cho worker role (tùy chọn)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--artifact-dir", default=str(Path("artifacts") / "store"))
    serve.add_argument("--shared-origin", action="append", default=[], help="Origin allowlist cho shared profile")
    serve.set_defaults(handler="serve")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    interrupt_after_polls: int | None = None,
) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    as_json = "--json" in (argv if argv is not None else sys.argv[1:])
    try:
        args = build_parser().parse_args(argv)
    except CliInputError as error:
        _fail("input_invalid", str(error), as_json=as_json)
        return EXIT_INVALID
    except SystemExit as error:
        return int(error.code or 0)

    args.json_output = bool(getattr(args, "json_output", False))
    args.interrupt_after_polls = interrupt_after_polls
    handler = args.handler
    try:
        if handler == "config-validate":
            return _command_config_validate(args, as_json=args.json_output)
        if handler == "calibration-validate":
            return _command_calibration_validate(args, as_json=args.json_output)
        if handler == "calibration-status":
            return _command_calibration_status(args, as_json=args.json_output)
        if handler == "calibration-execute":
            return _command_calibration_execute(args, as_json=args.json_output)
        if handler == "experiment-validate":
            return _command_experiment_validate(args, as_json=args.json_output)
        if handler == "experiment-execute":
            return _command_experiment_execute(args, as_json=args.json_output)
        if handler == "experiment-recompute":
            return _command_experiment_recompute(args, as_json=args.json_output)
        if handler == "serve":
            return _command_serve(args)
        token = _resolve_token(args.token_env)
        with _build_client(args.base_url, token) as client:
            if handler == "export":
                return _command_export(args, client, as_json=args.json_output)
            if handler == "import":
                return _command_import(args, client, as_json=args.json_output)
            if handler in ("run-submit", "suite-submit"):
                return _command_submit(args, client)
            if handler == "run-get":
                return _command_run_get(args, client)
            if handler == "run-result":
                return _command_run_result(args, client)
            if handler == "run-wait":
                return _command_run_wait(args, client)
            if handler == "run-cancel":
                return _command_run_cancel(args, client)
            if handler == "suite-bind":
                return _command_suite_bind(args, client)
            raise CliInputError(f"Lệnh không hỗ trợ: {handler}")
    except CliInputError as error:
        _fail("input_invalid", str(error), as_json=args.json_output, payload=error.payload)
        return EXIT_INVALID
    except KeyboardInterrupt:
        return EXIT_CANCELLED
