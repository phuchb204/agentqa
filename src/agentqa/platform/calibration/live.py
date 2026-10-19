from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import os
import secrets
import socket
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from agentqa.contracts.calibration import CalibrationProfile
from agentqa.contracts.canonical import digest_content
from agentqa.contracts.observation import Modality
from agentqa.platform.evaluation import EvaluationService
from agentqa.platform.runs.coordinator import ExecutionOutcome, ExecutionSpec, outcome_from_dict
from agentqa.platform.runs.read_models import RunReadModel
from agentqa.platform.runs.service import RunService, SubmitRequest
from agentqa.platform.runs.worker import RunWorker
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.migrate import upgrade
from agentqa.platform.storage.roles import (
    ROLE_API,
    ROLE_EVALUATOR,
    ROLE_MIGRATE,
    ROLE_SUPERVISOR,
    ROLE_WORKER,
    admin_dsn,
    bootstrap_profile,
    create_database,
    drop_database,
    role_dsn,
)
from agentqa.platform.storage.scope import set_scope
from agentqa.platform.usage.service import UsageLedgerService

REPO_ROOT = Path(__file__).resolve().parents[4]
BASELINE_DIR = REPO_ROOT / "benchmarks" / "public" / "baselines" / "visual"


def _run_db(coro):
    loop: asyncio.AbstractEventLoop = (
        asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    )
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


@dataclass
class LiveApp:
    name: str
    base_url: str
    control_token: str
    server: Any = None
    thread: Any = None

    @property
    def fixture_ref(self) -> str:
        return f"{self.name}@1"


@dataclass(frozen=True)
class LiveCaseRun:
    run_id: UUID
    state: dict[str, Any]
    usage: dict[str, Any]


class SupervisorClient:
    def __init__(self, host: str, port: int, token: str, *, timeout: float = 1800.0) -> None:
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._reader = self._sock.makefile("r", encoding="utf-8")
        self._writer = self._sock.makefile("w", encoding="utf-8")
        self._writer.write(json.dumps({"token": token}) + "\n")
        self._writer.flush()
        hello = json.loads(self._reader.readline())
        if not hello.get("ok"):
            raise RuntimeError(f"supervisor từ chối kết nối: {hello}")

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._writer.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._writer.flush()
        response = json.loads(self._reader.readline())
        if not response.get("ok"):
            raise RuntimeError(f"supervisor lỗi: {response.get('error')}")
        return response["result"]

    def close_socket(self) -> None:
        self._reader.close()
        self._writer.close()
        self._sock.close()


class RemoteCoordinator:
    def __init__(self, client: SupervisorClient) -> None:
        self._client = client

    async def execute(self, spec: ExecutionSpec) -> ExecutionOutcome:
        result = await asyncio.to_thread(self._client.request, _spec_payload(spec))
        return outcome_from_dict(result)

    async def apply_control(self, control_id: UUID) -> dict[str, Any]:
        return await asyncio.to_thread(self._client.request, {"op": "apply_control", "control_id": str(control_id)})


def _spec_payload(spec: ExecutionSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "op": "run_execution",
        "workspace_id": str(spec.workspace_id),
        "principal_id": str(spec.principal_id),
        "run_id": str(spec.run_id),
        "execution_id": str(spec.execution_id),
        "attempt_id": str(spec.attempt_id),
        "logical_key": spec.logical_key,
        "case": spec.case.model_dump(mode="json"),
        "target_base_url": spec.target_base_url,
        "fixture_ref": spec.fixture_ref,
        "namespace": spec.namespace,
        "fixture_seed": spec.fixture_seed,
        "parameters": spec.parameters,
        "gate_profile": spec.gate_profile,
        "fence_epoch": spec.fence_epoch,
        "policy": spec.policy,
        "observation_mode": spec.observation_mode,
        "snapshot_digest": spec.snapshot_digest,
        "provisional": spec.provisional,
    }
    if spec.healing_profile is not None:
        payload["healing_profile"] = spec.healing_profile.model_dump(mode="json")
    if spec.case_id is not None:
        payload["case_id"] = str(spec.case_id)
    if spec.case_revision_id is not None:
        payload["case_revision_id"] = str(spec.case_revision_id)
    return payload


class ProfileWorker(RunWorker):
    healing_profile: CalibrationProfile | None = None
    last_outcome: Any = None

    async def _load(self, execution_id: UUID) -> ExecutionSpec:
        spec = await super()._load(execution_id)
        if self.healing_profile is None:
            return spec
        return dataclasses.replace(spec, healing_profile=self.healing_profile)

    async def _finalize(self, spec: ExecutionSpec, outcome: ExecutionOutcome) -> None:
        self.last_outcome = outcome
        await super()._finalize(spec, outcome)


@dataclass
class LiveResearchHarness:
    apps: list[LiveApp]
    root: Path
    ref_resolver: Callable[[str, str, str], str | None] | None = None
    extra_env: dict[str, str] = field(default_factory=dict)
    db_name: str = ""
    workspace_id: UUID | None = None
    user_id: UUID | None = None
    username: str = ""
    password: str = ""
    supervisor: subprocess.Popen | None = None
    client: SupervisorClient | None = None
    worker: ProfileWorker | None = None
    _engines: dict[str, AsyncEngine] = field(default_factory=dict)
    _log_lines: list[str] = field(default_factory=list)

    def start(self) -> None:
        self.db_name = f"agentqa_research_{secrets.token_hex(4)}"
        admin = admin_dsn()
        _run_db(bootstrap_profile(admin))
        _run_db(create_database(admin, self.db_name))
        _run_db(upgrade(role_dsn(ROLE_MIGRATE, self.db_name)))
        self._engines = {
            role: create_async_engine(role_dsn(role, self.db_name), pool_size=5, max_overflow=5)
            for role in (ROLE_API, ROLE_WORKER, ROLE_SUPERVISOR, ROLE_EVALUATOR)
        }
        _run_db(self._seed_workspace())
        self._start_supervisor()
        self._start_worker()

    async def _seed_workspace(self) -> None:
        from agentqa.platform.api.runtime import PlatformRuntime, RuntimeProfile
        from agentqa.platform.artifacts.store import FileSystemBlobStore

        runtime = PlatformRuntime.build(
            profile=RuntimeProfile.local(),
            dsn_by_role={ROLE_API: role_dsn(ROLE_API, self.db_name), ROLE_WORKER: role_dsn(ROLE_WORKER, self.db_name)},
            artifact_store=FileSystemBlobStore(self.root / "blobs"),
        )
        try:
            self.username = f"research-{secrets.token_hex(4)}"
            self.password = "pw-research-123456"
            user = await runtime.users.create(username=self.username, password=self.password)
            workspace = await runtime.authorization.create_workspace(
                actor_id=user.id, slug=f"res-{secrets.token_hex(4)}", name="Research live"
            )
            self.user_id = user.id
            self.workspace_id = workspace.id
        finally:
            await runtime.aclose()

    def _start_supervisor(self) -> None:
        assert self.workspace_id is not None and self.user_id is not None
        token = secrets.token_urlsafe(16)
        command = [
            sys.executable,
            "-m",
            "agentqa.platform.supervisor.entrypoint",
            "--dsn",
            role_dsn(ROLE_SUPERVISOR, self.db_name),
            "--workspace-id",
            str(self.workspace_id),
            "--principal-id",
            str(self.user_id),
            "--supervisor-id",
            "live-research",
            "--control-token",
            token,
            "--agent-models",
            "live",
        ]
        for app in self.apps:
            host_port = app.base_url.split("//", 1)[1]
            command.extend(["--allow-origin", host_port])
            command.extend(["--fixture-endpoint", f"{app.name}@1|{app.base_url}|{app.control_token}"])
        if BASELINE_DIR.is_dir():
            command.extend(["--baseline-dir", str(BASELINE_DIR)])
        environment = {**os.environ, **self.extra_env}
        self.supervisor = subprocess.Popen(
            command,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        line = self.supervisor.stdout.readline()
        if not line:
            error = self.supervisor.stderr.read() if self.supervisor.stderr else ""
            raise RuntimeError(f"supervisor live không khởi động: {error[:400]}")
        payload = json.loads(line)
        self.client = SupervisorClient("127.0.0.1", int(payload["port"]), token)

    def _start_worker(self) -> None:
        assert self.workspace_id is not None and self.user_id is not None
        from agentqa.platform.queue import JobQueue

        engine = self._engines[ROLE_WORKER]
        queue = JobQueue(
            create_session_factory(engine),
            workspace_id=self.workspace_id,
            principal_id=self.user_id,
            slot_capacity=1,
        )
        assert self.client is not None
        from agentqa.platform.runs.coordinator import RunEventRecorder

        self.worker = ProfileWorker(
            queue=queue,
            coordinator=RemoteCoordinator(self.client),
            recorder=RunEventRecorder(engine),
            engine=engine,
            principal_id=self.user_id,
            workspace_id=self.workspace_id,
            worker_id="live-research-worker",
        )

    def seed_case(self, *, logical_key: str, document: dict[str, Any]) -> UUID:
        assert self.workspace_id is not None and self.user_id is not None

        async def promote() -> UUID:
            from agentqa.platform.api.runtime import PlatformRuntime, RuntimeProfile
            from agentqa.platform.artifacts.store import FileSystemBlobStore

            runtime = PlatformRuntime.build(
                profile=RuntimeProfile.local(),
                dsn_by_role={
                    ROLE_API: role_dsn(ROLE_API, self.db_name),
                    ROLE_WORKER: role_dsn(ROLE_WORKER, self.db_name),
                },
                artifact_store=FileSystemBlobStore(self.root / "blobs"),
            )
            try:
                entity = await runtime.revisions.create_entity(
                    workspace_id=self.workspace_id,
                    principal_id=self.user_id,
                    kind="case",
                    logical_key=logical_key,
                )
                receipt = await runtime.revisions.promote_content(
                    workspace_id=self.workspace_id,
                    principal_id=self.user_id,
                    actor=self.username,
                    kind="case",
                    entity_id=entity.id,
                    content=document,
                )
                return receipt.revision_id
            finally:
                await runtime.aclose()

        return _run_db(promote())

    def seed_environment(
        self, *, app: LiveApp, namespace: str, parameters: dict[str, Any], fixture_seed: str | None = None
    ) -> UUID:
        assert self.workspace_id is not None and self.user_id is not None
        application_id = uuid4()
        revision_id = uuid4()
        content = {
            "target_base_url": f"{app.base_url}/{namespace}",
            "fixture_ref": app.fixture_ref,
            "namespace": namespace,
            "parameters": parameters,
        }
        if fixture_seed is not None:
            content["fixture_seed"] = fixture_seed

        async def insert() -> UUID:
            factory = create_session_factory(self._engines[ROLE_API])
            async with factory() as session, session.begin():
                await set_scope(session, principal_id=self.user_id, workspace_id=self.workspace_id)
                await session.execute(
                    sa.insert(tables.applications).values(
                        id=application_id,
                        workspace_id=self.workspace_id,
                        slug=f"app-{application_id.hex[:8]}",
                        name=f"research-{app.name}",
                    )
                )
                await session.execute(
                    sa.insert(tables.environment_revisions).values(
                        id=revision_id,
                        workspace_id=self.workspace_id,
                        application_id=application_id,
                        revision_no=1,
                        content=content,
                        content_digest=digest_content(content),
                        lifecycle="ready",
                        author=self.username,
                    )
                )
            return revision_id

        return _run_db(insert())

    def prepare_namespace(self, app: LiveApp, namespace: str, seed: str) -> None:
        from agentqa.platform.fixtures import CanvasdeskFixture, ShopflowFixture, TaskboardFixture

        factories = {
            "taskboard": TaskboardFixture,
            "shopflow": ShopflowFixture,
            "canvasdesk": CanvasdeskFixture,
        }
        receipt = factories[app.name](app.base_url, app.control_token).prepare(namespace, seed)
        if not receipt.ok:
            raise RuntimeError(f"fixture prepare thất bại: {receipt.detail}")

    def apply_mutation(self, app: LiveApp, namespace: str, operator: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._control(app, "POST", f"/namespaces/{namespace}/mutate", {"operator": operator, "params": params})

    def arm_mutation(self, app: LiveApp, namespace: str, operator: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._control(
            app, "POST", f"/namespaces/{namespace}/mutation-intent", {"operator": operator, "params": params}
        )

    def _control(self, app: LiveApp, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        header = {
            "taskboard": "x-taskboard-control",
            "shopflow": "x-shopflow-control",
            "canvasdesk": "x-canvasdesk-control",
        }[app.name]
        with httpx.Client(timeout=30.0, headers={header: app.control_token}) as client:
            response = client.request(method, f"{app.base_url}/_control{path}", json=payload)
        response.raise_for_status()
        return response.json()

    def run_case(
        self,
        *,
        case_revision_id: UUID,
        environment_revision_id: UUID,
        policy: str,
        observation: str,
        healing_profile: CalibrationProfile | None = None,
        gate_profile: str = "strict",
    ) -> LiveCaseRun:
        assert self.workspace_id is not None and self.user_id is not None and self.worker is not None

        async def execute() -> UUID:
            service = RunService(self._engines[ROLE_API])
            outcome = await service.submit(
                SubmitRequest(
                    workspace_id=self.workspace_id,
                    principal_id=self.user_id,
                    actor=self.username,
                    idempotency_key=uuid4().hex,
                    case_revision_ids=(case_revision_id,),
                    environment_revision_id=environment_revision_id,
                    provided_capabilities=frozenset(),
                    policy=policy,
                    observation_mode=Modality(observation),
                    gate_profile=gate_profile,
                )
            )
            await self._seed_attempt(outcome.run_id)
            self.worker.healing_profile = healing_profile
            summaries = await self.worker.run_until_idle(max_jobs=5)
            if not summaries:
                raise RuntimeError("worker không chạy execution nào")
            return outcome.run_id

        run_id = _run_db(execute())
        state = self.run_state(run_id)
        usage = self.usage_snapshot(run_id)
        return LiveCaseRun(run_id=run_id, state=state, usage=usage)

    async def _seed_attempt(self, run_id: UUID) -> None:
        factory = create_session_factory(self._engines[ROLE_WORKER])
        async with factory() as session, session.begin():
            await set_scope(session, principal_id=self.user_id, workspace_id=self.workspace_id)
            executions = (
                await session.execute(
                    sa.select(tables.executions.c.id).where(
                        tables.executions.c.workspace_id == self.workspace_id,
                        tables.executions.c.run_id == run_id,
                    )
                )
            ).all()
            for row in executions:
                await session.execute(
                    sa.insert(tables.attempts).values(
                        workspace_id=self.workspace_id,
                        execution_id=row.id,
                        attempt_no=1,
                        status="running",
                        fence_epoch=1,
                    )
                )

    def abort_reason(self, run_id: UUID) -> str | None:
        assert self.workspace_id is not None and self.user_id is not None

        async def fetch() -> str | None:
            from agentqa.platform.events.service import EventService

            events = await EventService(self._engines[ROLE_API]).query_durable(
                workspace_id=self.workspace_id,
                principal_id=self.user_id,
                run_id=run_id,
                limit=500,
            )
            for event in reversed(events):
                if event["type"] == "execution.aborted":
                    summary = event.get("summary") or {}
                    return str(summary.get("reason"))
            return None

        return _run_db(fetch())

    def run_state(self, run_id: UUID) -> dict[str, Any]:
        assert self.workspace_id is not None and self.user_id is not None

        async def fetch() -> dict[str, Any]:
            model = RunReadModel(self._engines[ROLE_API])
            state = await model.run_state(workspace_id=self.workspace_id, principal_id=self.user_id, run_id=run_id)
            if state is None:
                raise RuntimeError(f"run {run_id} không tồn tại")
            return state

        return _run_db(fetch())

    def usage_snapshot(self, run_id: UUID) -> dict[str, Any]:
        assert self.workspace_id is not None and self.user_id is not None

        async def fetch() -> dict[str, Any]:
            usage = UsageLedgerService()
            factory = create_session_factory(self._engines[ROLE_API])
            async with factory() as session, session.begin():
                await set_scope(session, principal_id=self.user_id, workspace_id=self.workspace_id)
                phases = await usage.usage_by_phase(session, workspace_id=self.workspace_id, run_id=run_id)
                wall = await usage.wall_time_seconds(session, workspace_id=self.workspace_id, run_id=run_id)
                aggregate = await usage.aggregate_run(session, workspace_id=self.workspace_id, run_id=run_id)
                calls = (
                    await session.execute(
                        sa.select(
                            tables.model_calls.c.requested_model,
                            tables.model_calls.c.resolved_model,
                            tables.model_calls.c.usage_cached,
                            tables.model_calls.c.record_state,
                        ).where(
                            tables.model_calls.c.workspace_id == self.workspace_id,
                            tables.model_calls.c.run_id == run_id,
                        )
                    )
                ).all()
            totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0}
            for bucket in phases.values():
                totals["calls"] += bucket["calls"]
                totals["input_tokens"] += bucket["input_tokens"]
                totals["output_tokens"] += bucket["output_tokens"]
                totals["cached_tokens"] += bucket["cached_tokens"]
            requested = sorted({row.requested_model for row in calls})
            resolved = sorted({row.resolved_model for row in calls if row.resolved_model})
            return {
                **totals,
                "wall_time_seconds": wall.get("wall_time_seconds", 0.0),
                "unknown_intervals": wall.get("unknown_intervals", 0),
                "model_requested": requested,
                "model_resolved": resolved,
                "provider_cache_observed": totals["cached_tokens"] > 0,
                "cost_bases": sorted({entry.basis for entry in aggregate.entries}),
                "cost_state": aggregate.state,
                "cost_total": [str(entry.total) for entry in aggregate.entries if entry.total is not None],
            }

        return _run_db(fetch())

    def score_run(self, run_id: UUID, oracle: dict[str, Any]) -> dict[str, Any]:
        assert self.workspace_id is not None and self.user_id is not None

        async def evaluate() -> dict[str, Any]:
            from agentqa.platform.evaluation import OracleOpportunity, OracleRecord, VariantClassification

            service = EvaluationService(self._engines[ROLE_EVALUATOR], ref_resolver=self.ref_resolver)
            record = OracleRecord(
                case_key=str(oracle["case_key"]),
                variant_token=oracle.get("variant_token"),
                app=str(oracle["app"]),
                fixture_ref=str(oracle["fixture_ref"]),
                classification=VariantClassification(str(oracle.get("classification", "benign"))),
                expected_effects=list(oracle.get("expected_effects", [])),
                opportunities=[
                    OracleOpportunity(
                        opportunity_id=item["opportunity_id"],
                        step_id=item["step_id"],
                        original_identity=item["original_identity"],
                        expected_identity=item.get("expected_identity"),
                        expected_entity=item.get("expected_entity"),
                        kind=item.get("kind", "mismatch"),
                    )
                    for item in oracle.get("opportunities", [])
                ],
            )
            return await service.evaluate_run(
                workspace_id=self.workspace_id,
                principal_id=self.user_id,
                run_id=run_id,
                oracle=record,
            )

        return _run_db(evaluate())

    def stop(self) -> None:
        if self.worker is not None:
            self.worker = None
        if self.client is not None:
            self.client.close_socket()
            self.client = None
        if self.supervisor is not None:
            self.supervisor.terminate()
            try:
                self.supervisor.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.supervisor.kill()
            self.supervisor = None
        for engine in self._engines.values():
            _run_db(engine.dispose())
        self._engines = {}
        if self.db_name:
            with contextlib.suppress(Exception):
                _run_db(drop_database(admin_dsn(), self.db_name))


class _NullRecorder:
    async def record(self, **kwargs: Any) -> None:
        return None


def start_benchmark_apps() -> list[LiveApp]:
    import threading
    import time

    import uvicorn

    apps: list[LiveApp] = []
    factories: dict[str, tuple[str, str]] = {
        "taskboard": ("taskboard", "create_taskboard_app"),
        "shopflow": ("shopflow", "create_shopflow_app"),
        "canvasdesk": ("canvasdesk", "create_canvasdesk_app"),
    }
    for name, (module_name, factory_name) in factories.items():
        app_path = str(REPO_ROOT / "benchmarks" / "apps" / name)
        if app_path not in sys.path:
            sys.path.insert(0, app_path)
        module = __import__(module_name)
        factory = getattr(module, factory_name)
        token = secrets.token_urlsafe(16)
        server = uvicorn.Server(uvicorn.Config(factory(token), host="127.0.0.1", port=0, log_level="warning"))
        thread = threading.Thread(target=server.run, name=f"research-{name}", daemon=True)
        thread.start()
        deadline = time.monotonic() + 20
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError(f"{name} không khởi động")
            time.sleep(0.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        apps.append(
            LiveApp(name=name, base_url=f"http://127.0.0.1:{port}", control_token=token, server=server, thread=thread)
        )
    return apps


def stop_benchmark_apps(apps: list[LiveApp]) -> None:
    for app in apps:
        if app.server is not None:
            app.server.should_exit = True
        if app.thread is not None:
            app.thread.join(timeout=10)


def load_private_oracle():
    import importlib

    private_root = REPO_ROOT / "benchmarks" / "private"
    if str(private_root) not in sys.path:
        sys.path.insert(0, str(private_root))
    return importlib.import_module(os.environ.get("AGENTQA_ORACLE_MODULE", "oracle"))


def research_ref_resolver(oracle_module) -> Callable[[str, str, str], str | None]:
    def resolve(app: str, namespace: str, ref: str) -> str | None:
        if app == "taskboard":
            return ref if ref.startswith(("item-", "line-", "upload-", "job-", "order-")) else None
        return oracle_module.resolve_ref(app, namespace, ref)

    return resolve


LIVE_CALIBRATION_CASES: dict[str, dict[str, Any]] = {
    "taskboard-delete": {
        "app": "taskboard",
        "case_key": "taskboard_delete_item_healed",
        "seed": "success",
        "operator": "rename_label",
        "params": {"from": "Xoá", "to": "Xoá cũ"},
        "run_params": {"item_name": "Việc hiệu chuẩn"},
    },
    "taskboard-ambiguous": {
        "app": "taskboard",
        "case_key": "taskboard_delete_item_healed",
        "seed": "duplicate_rejected",
        "operator": "duplicate_label",
        "params": {"label": "Việc trùng"},
        "run_params": {"item_name": "Việc trùng"},
    },
    "taskboard-pilot": {
        "app": "taskboard",
        "case_key": "taskboard_delete_item_healed",
        "seed": "success",
        "operator": "rename_label",
        "params": {"from": "Xoá", "to": "Xoá cũ"},
        "run_params": {"item_name": "Việc pilot"},
    },
}


def _labels_from_scoring(scoring: dict[str, Any]) -> dict[str, Any]:
    counters = scoring.get("counters") or {}
    false_heal = int(counters.get("false_heals", 0)) > 0
    correct_heal = int(counters.get("correct_heals", 0)) > 0
    refusal = int(counters.get("refusals", 0)) > 0
    unscorable = int(counters.get("unscorable_attempts", 0)) > 0 and not (false_heal or correct_heal or refusal)
    if not (false_heal or correct_heal or refusal or unscorable):
        unscorable = int(counters.get("attempts_total", 0)) == 0
    return {
        "false_heal": false_heal,
        "correct_heal": correct_heal,
        "refusal": refusal,
        "unscorable": unscorable,
        "synthetic": False,
    }


def _case_document(case_key: str) -> dict[str, Any]:
    import yaml

    for path in sorted((REPO_ROOT / "benchmarks" / "public" / "cases").rglob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(document, dict) and document.get("logical_key") == case_key:
            return document
    raise KeyError(f"không tìm thấy case '{case_key}' trong corpus")


def run_live_calibration(
    manifest,
    harness: LiveResearchHarness,
    oracle_module,
    *,
    candidate_limit: int | None = None,
    cases_per_family: int | None = None,
) -> dict[str, Any]:
    from agentqa.contracts.calibration import RankerKind
    from agentqa.platform.calibration.jobs import enumerate_candidates
    from agentqa.platform.calibration.models import CalibrationTrial, TrialLabels
    from agentqa.platform.calibration.profiles import build_receipt, rank_candidates
    from agentqa.platform.statistics.samples import (
        sample_size_from_conservative_bound,
        sample_size_from_pilot_rows,
    )

    candidates = enumerate_candidates(manifest)
    if candidate_limit is not None:
        candidates = candidates[:candidate_limit]
    apps = {app.name: app for app in harness.apps}
    case_revisions: dict[str, UUID] = {}
    trials: list[CalibrationTrial] = []
    call_budget = manifest.budgets.max_calls
    calls_used = 0
    skipped: list[str] = []

    def ensure_case(spec: dict[str, Any]) -> UUID:
        case_key = str(spec["case_key"])
        if case_key not in case_revisions:
            document = _case_document(case_key)
            case_revisions[case_key] = harness.seed_case(logical_key=case_key, document=document)
        return case_revisions[case_key]

    def profile_for(candidate) -> CalibrationProfile:
        return CalibrationProfile(
            profile_id=f"live-{candidate.candidate_id}",
            version="live",
            ranker=RankerKind(candidate.ranker),
            min_score=float(candidate.params.get("min_score", 0.55)),
            margin_min=float(candidate.params.get("margin_min", 0.15)),
            max_candidates=int(candidate.params.get("max_candidates", 24)),
        )

    def run_trial(candidate, key: str, split: str) -> CalibrationTrial | None:
        nonlocal calls_used
        family = key.split(":", 1)[0]
        spec = LIVE_CALIBRATION_CASES.get(family)
        if spec is None:
            skipped.append(f"{key}:no_live_mapping")
            return None
        if calls_used >= call_budget:
            skipped.append(f"{key}:budget_exceeded")
            return None
        app = apps[str(spec["app"])]
        slug = candidate.candidate_id.replace(".", "_")[:24]
        namespace = f"cal-{family}-{slug}-{uuid4().hex[:6]}"
        armed = harness.arm_mutation(app, namespace, str(spec["operator"]), dict(spec["params"]))
        if not armed.get("armed"):
            skipped.append(f"{key}:variant_{armed.get('reason')}")
            return None
        revision = ensure_case(spec)
        environment = harness.seed_environment(
            app=app,
            namespace=namespace,
            parameters=dict(spec["run_params"]),
            fixture_seed=str(spec["seed"]),
        )
        run = harness.run_case(
            case_revision_id=revision,
            environment_revision_id=environment,
            policy="replay_healing",
            observation="semantic",
            healing_profile=profile_for(candidate),
        )
        calls_used += int(run.usage.get("calls", 0))
        oracle_record = oracle_module.variant_oracle_record(
            {
                "variant_token": f"cal-{digest_content([candidate.candidate_id, key])[:16]}",
                "case_key": str(spec["case_key"]),
                "app": app.name,
                "operator": {"name": str(spec["operator"]), "version": 1, "group": "benign"},
                "params": dict(spec["params"]),
                "applied_patch": dict(spec["params"]),
                "valid": True,
            }
        )
        scoring = harness.score_run(run.run_id, oracle_record)
        return CalibrationTrial(
            candidate_id=candidate.candidate_id,
            case_key=key,
            family=family,
            split=split,
            labels=TrialLabels(**_labels_from_scoring(scoring)),
        )

    for candidate in candidates:
        for key in manifest.splits["calibration"]:
            trial = run_trial(candidate, key, "calibration")
            if trial is not None:
                trials.append(trial)
    ranking = rank_candidates(candidates, trials, manifest)
    winner_id = ranking[0]["candidate_id"] if ranking else None
    winner = next(candidate for candidate in candidates if candidate.candidate_id == winner_id)
    pilot_rates: list[float] = []
    for key in manifest.splits.get("pilot", []):
        trial = run_trial(winner, key, "pilot")
        if trial is not None:
            trials.append(trial)
            pilot_rates.append(1.0 if trial.labels.false_heal else 0.0)
    if pilot_rates:
        sample_size = sample_size_from_pilot_rows(pilot_rates, precision=0.01).as_dict()
    else:
        sample_size = sample_size_from_conservative_bound(
            manifest.quality_policy.max_false_heal_rate, confidence=manifest.quality_policy.confidence
        ).as_dict()
    receipt = build_receipt(manifest, winner, trials, ranking=ranking, sample_size=sample_size)
    return {
        "receipt": receipt,
        "trials": [trial.model_dump(mode="json") for trial in trials],
        "calls_used": calls_used,
        "skipped": skipped,
        "winner": winner.candidate_id,
    }


def _render_template(value: Any, *, index: int, seed: int) -> Any:
    if isinstance(value, str):
        return value.replace("{index}", f"{index:03d}").replace("{seed}", str(seed))
    if isinstance(value, dict):
        return {key: _render_template(item, index=index, seed=seed) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_template(item, index=index, seed=seed) for item in value]
    return value


def expand_verification_trials(plan) -> list[tuple[str, int, int]]:
    import random

    combos = [
        (family, item, seed) for family in plan.families for item in range(plan.items_per_family) for seed in plan.seeds
    ]
    shuffler = random.Random(plan.shuffle_seed)
    shuffler.shuffle(combos)
    return combos


def run_live_verification(
    manifest,
    harness: LiveResearchHarness,
    oracle_module,
    *,
    trial_limit: int | None = None,
) -> dict[str, Any]:
    from agentqa.contracts.calibration import CalibrationProfile, RankerKind
    from agentqa.platform.calibration.models import CalibrationTrial, CandidateResult, TrialLabels
    from agentqa.platform.calibration.profiles import build_verification_receipt
    from agentqa.platform.statistics.samples import sample_size_from_conservative_bound

    plan = manifest.verification
    if plan is None:
        raise ValueError("manifest thiếu verification plan")
    profile = CalibrationProfile(
        profile_id=f"verify-{plan.candidate_id}",
        version="verify",
        ranker=RankerKind(plan.ranker),
        min_score=float(plan.min_score),
        margin_min=float(plan.margin_min),
        max_candidates=int(plan.max_candidates),
    )
    apps = {app.name: app for app in harness.apps}
    case_revisions: dict[str, UUID] = {}
    trials: list[CalibrationTrial] = []
    calls_used = 0
    skipped: list[str] = []
    combos = expand_verification_trials(plan)
    if trial_limit is not None:
        combos = combos[:trial_limit]

    def ensure_case(spec: dict[str, Any]) -> UUID:
        case_key = str(spec["case_key"])
        if case_key not in case_revisions:
            document = _case_document(case_key)
            case_revisions[case_key] = harness.seed_case(logical_key=case_key, document=document)
        return case_revisions[case_key]

    for family, item, seed in combos:
        if calls_used >= manifest.budgets.max_calls:
            skipped.append(f"{family}:{item}:{seed}:budget_exceeded")
            continue
        spec = LIVE_CALIBRATION_CASES.get(family)
        if spec is None:
            skipped.append(f"{family}:{item}:{seed}:no_live_mapping")
            continue
        app = apps.get(str(spec["app"]))
        if app is None:
            skipped.append(f"{family}:{item}:{seed}:app_missing")
            continue
        namespace = f"calv-{family}-{item:03d}-{seed}-{uuid4().hex[:6]}"
        armed = harness.arm_mutation(app, namespace, str(spec["operator"]), dict(spec["params"]))
        if not armed.get("armed"):
            skipped.append(f"{family}:{item}:{seed}:variant_{armed.get('reason')}")
            continue
        revision = ensure_case(spec)
        run_params = dict(_render_template(dict(spec["run_params"]), index=item, seed=seed))
        run_params.setdefault("item_name", f"Vật hiệu chuẩn {item:03d}-{seed}")
        environment = harness.seed_environment(
            app=app,
            namespace=namespace,
            parameters=run_params,
            fixture_seed=f"{spec['seed']}-{seed}",
        )
        run = harness.run_case(
            case_revision_id=revision,
            environment_revision_id=environment,
            policy="replay_healing",
            observation="semantic",
            healing_profile=profile,
        )
        calls_used += int(run.usage.get("calls", 0))
        oracle_record = oracle_module.variant_oracle_record(
            {
                "variant_token": f"calv-{digest_content([plan.candidate_id, family, item, seed])[:16]}",
                "case_key": str(spec["case_key"]),
                "app": app.name,
                "operator": {"name": str(spec["operator"]), "version": 1, "group": "benign"},
                "params": dict(spec["params"]),
                "applied_patch": dict(spec["params"]),
                "valid": True,
            }
        )
        scoring = harness.score_run(run.run_id, oracle_record)
        trials.append(
            CalibrationTrial(
                candidate_id=plan.candidate_id,
                case_key=f"{family}:verify-{item:03d}-{seed}",
                family=family,
                split="verification",
                labels=TrialLabels(**_labels_from_scoring(scoring)),
            )
        )
    receipt = build_verification_receipt(
        manifest,
        CandidateResult(
            candidate_id=plan.candidate_id,
            ranker=RankerKind(plan.ranker),
            params={"min_score": plan.min_score, "margin_min": plan.margin_min, "max_candidates": plan.max_candidates},
        ),
        trials,
        sample_size=sample_size_from_conservative_bound(
            manifest.quality_policy.max_false_heal_rate, confidence=manifest.quality_policy.confidence
        ).as_dict(),
    )
    return {
        "receipt": receipt,
        "trials": [trial.model_dump(mode="json") for trial in trials],
        "calls_used": calls_used,
        "skipped": skipped,
        "winner": plan.candidate_id,
    }
