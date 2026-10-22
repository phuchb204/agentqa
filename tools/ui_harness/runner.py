from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import sqlalchemy as sa
import uvicorn
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tools.ui_harness.authoring_model import HarnessAuthoringGo
from tools.ui_harness.supervisor import (
    SupervisorProcess,
    free_port,
    sanitized_environment,
    start_supervisor,
    wait_for_http,
)

from agentqa.contracts.canonical import digest_content
from agentqa.platform.api.application import create_application
from agentqa.platform.api.runtime import PlatformRuntime, RuntimeProfile
from agentqa.platform.artifacts.store import FileSystemBlobStore
from agentqa.platform.events.service import EventService
from agentqa.platform.queue import JobQueue
from agentqa.platform.runs.coordinator import ExecutionSpec, RunEventRecorder
from agentqa.platform.runs.service import RunService, SubmitRequest
from agentqa.platform.runs.worker import RunWorker
from agentqa.platform.security.taint import TaintRegistry
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import configure_event_loop_policy, create_session_factory
from agentqa.platform.storage.migrate import upgrade
from agentqa.platform.storage.roles import (
    ROLE_API,
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

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "ui-e2e"
ITEM_NAME = "Việc UI E2E"
CANARY_KEY = "agentqa-ui-canary-key-7f21"

configure_event_loop_policy()


class HarnessError(RuntimeError):
    pass


@dataclass
class HarnessCheck:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class HarnessReport:
    ok: bool
    checks: list[HarnessCheck] = field(default_factory=list)
    workspace_id: str = ""
    run_id: str = ""
    run_verdict: str | None = None
    draft_run_verdict: str | None = None
    artifacts_dir: str = ""
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [{"name": check.name, "ok": check.ok, "detail": check.detail} for check in self.checks],
            "workspace_id": self.workspace_id,
            "run_id": self.run_id,
            "run_verdict": self.run_verdict,
            "draft_run_verdict": self.draft_run_verdict,
            "artifacts_dir": self.artifacts_dir,
            "error": self.error,
        }


def _run_db(coro: Any) -> Any:
    if sys.platform == "win32":
        loop: asyncio.AbstractEventLoop = asyncio.SelectorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class HarnessWorker(RunWorker):
    def __init__(self, *, healing_profile=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._healing_profile = healing_profile

    async def _load(self, execution_id: UUID) -> ExecutionSpec:
        await self._ensure_attempt(execution_id)
        spec = await super()._load(execution_id)
        if self._healing_profile is None:
            return spec
        return dataclasses.replace(spec, healing_profile=self._healing_profile)

    async def _ensure_attempt(self, execution_id: UUID) -> None:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=self.principal_id, workspace_id=self.workspace_id)
            existing = (
                await session.execute(
                    sa.select(tables.attempts.c.id).where(tables.attempts.c.execution_id == execution_id)
                )
            ).one_or_none()
            if existing is None:
                await session.execute(
                    sa.insert(tables.attempts).values(
                        workspace_id=self.workspace_id,
                        execution_id=execution_id,
                        attempt_no=1,
                        status="running",
                        fence_epoch=1,
                    )
                )


class RemoteCoordinator:
    def __init__(self, supervisor: SupervisorProcess) -> None:
        self._supervisor = supervisor

    async def execute(self, spec: ExecutionSpec) -> Any:
        return await asyncio.to_thread(self._run_execution, spec)

    def _run_execution(self, spec: ExecutionSpec) -> Any:
        from agentqa.platform.runs.coordinator import outcome_from_dict

        client = self._supervisor.client()
        try:
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
            response = client.request(payload)
        finally:
            client.close_socket()
        if response.get("ok") is not True:
            raise HarnessError(f"supervisor run_execution lỗi: {response}")
        return outcome_from_dict(response["result"])

    async def apply_control(self, control_id: UUID) -> dict[str, Any]:
        client = self._supervisor.client()
        try:
            response = client.request({"op": "apply_control", "control_id": str(control_id)})
        finally:
            client.close_socket()
        return response.get("result", {})


@dataclass
class SeedResult:
    user_id: UUID
    username: str
    password: str
    workspace_id: UUID
    environment_revision_id: UUID
    namespace: str


class UiHarness:
    def __init__(
        self,
        *,
        scenario: str = "authoring",
        build_web: bool = True,
        agent_models: bool = False,
        agent_script: str | None = None,
    ) -> None:
        if scenario not in ("authoring", "live", "healing", "reporting", "admin", "experiments"):
            raise HarnessError(f"scenario không hỗ trợ: {scenario}")
        self.scenario = scenario
        self.build_web = build_web
        self.agent_models = agent_models
        self.agent_script = agent_script
        self.healing_profile = None
        self.db_name = f"agentqa_ui_{secrets.token_hex(4)}"
        self.workspace_root = REPO_ROOT / "artifacts" / "ui-e2e" / self.db_name
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.seed: SeedResult | None = None
        self.supervisor: SupervisorProcess | None = None
        self.api_server: uvicorn.Server | None = None
        self.api_thread: threading.Thread | None = None
        self.web_process: subprocess.Popen | None = None
        self.taskboard_server: uvicorn.Server | None = None
        self.taskboard_thread: threading.Thread | None = None
        self.taskboard_base_url = ""
        self.taskboard_control_token = ""
        self.worker_stop = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self.worker_errors: list[str] = []
        self.api_base_url = ""
        self.web_base_url = ""
        self.dsn_by_role: dict[str, str] = {}
        self.runtime: PlatformRuntime | None = None
        self.log_lines: list[str] = []
        self.seeded_case_revision: UUID | None = None

    def log(self, message: str) -> None:
        line = f"[{datetime.now(UTC).isoformat()}] {message}"
        self.log_lines.append(line)

    def start(self) -> None:
        admin = admin_dsn()
        try:
            _run_db(bootstrap_profile(admin))
        except Exception:
            self.log("docker compose up")
            subprocess.run(
                ["docker", "compose", "-f", "infra/compose.test.yml", "up", "-d", "--wait"],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
            )
            _run_db(bootstrap_profile(admin))
        _run_db(create_database(admin, self.db_name))
        self.dsn_by_role = {
            ROLE_API: role_dsn(ROLE_API, self.db_name),
            ROLE_WORKER: role_dsn(ROLE_WORKER, self.db_name),
            ROLE_SUPERVISOR: role_dsn(ROLE_SUPERVISOR, self.db_name),
        }
        _run_db(upgrade(role_dsn(ROLE_MIGRATE, self.db_name)))
        self.log("database ready")

        self._start_taskboard()
        self.seed = _run_db(self._seed())
        self.log(f"seeded workspace {self.seed.workspace_id}")

        supervisor_extra_args: list[str] = []
        if self.agent_models:
            supervisor_extra_args.append("--agent-models=fake")
        if self.agent_script:
            supervisor_extra_args.append(f"--agent-script={self.agent_script}")
        self.supervisor = start_supervisor(
            dsn=self.dsn_by_role[ROLE_SUPERVISOR],
            workspace_id=self.seed.workspace_id,
            principal_id=self.seed.user_id,
            taskboard_base_url=self.taskboard_base_url,
            taskboard_control_token=self.taskboard_control_token,
            extra_args=supervisor_extra_args or None,
        )
        self.log(f"supervisor port {self.supervisor.port}")

        self._start_api()
        self._start_web()
        self._start_worker()
        self.log("services started")

    def _start_taskboard(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "benchmarks" / "apps" / "taskboard"))
        from taskboard import create_taskboard_app

        self.taskboard_control_token = secrets.token_urlsafe(16)
        app = create_taskboard_app(self.taskboard_control_token)
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        self.taskboard_server = uvicorn.Server(config)
        self.taskboard_thread = threading.Thread(target=self.taskboard_server.run, daemon=True)
        self.taskboard_thread.start()
        deadline = time.monotonic() + 20
        while not self.taskboard_server.started:
            if time.monotonic() > deadline:
                raise HarnessError("taskboard không khởi động")
            time.sleep(0.05)
        port = self.taskboard_server.servers[0].sockets[0].getsockname()[1]
        self.taskboard_base_url = f"http://127.0.0.1:{port}"

    async def _seed(self) -> SeedResult:
        runtime = PlatformRuntime.build(
            profile=RuntimeProfile.local(),
            dsn_by_role={ROLE_API: self.dsn_by_role[ROLE_API], ROLE_WORKER: self.dsn_by_role[ROLE_WORKER]},
            artifact_store=FileSystemBlobStore(self.workspace_root / "blobs"),
            taint=TaintRegistry(),
            generative_model=HarnessAuthoringGo(),
        )
        try:
            username = f"ui-owner-{secrets.token_hex(4)}"
            password = "pw-ui-123456"
            user = await runtime.users.create(username=username, password=password)
            workspace = await runtime.authorization.create_workspace(
                actor_id=user.id, slug=f"ui-{secrets.token_hex(4)}", name="UI E2E"
            )
            requirement = await runtime.revisions.create_entity(
                workspace_id=workspace.id, principal_id=user.id, kind="requirement", logical_key="create_item"
            )
            await runtime.revisions.promote_content(
                workspace_id=workspace.id,
                principal_id=user.id,
                actor=username,
                kind="requirement",
                entity_id=requirement.id,
                content={
                    "schema_version": "requirement/1",
                    "logical_key": "create_item",
                    "text": "Người dùng tạo việc mới và việc xuất hiện đúng một lần",
                    "source_refs": ["flow_source"],
                    "acceptance_statements": ["Việc mới xuất hiện đúng một lần"],
                },
            )
            namespace = f"ui-{secrets.token_hex(4)}"
            environment_revision_id = await self._seed_environment(
                runtime, workspace_id=workspace.id, principal_id=user.id, namespace=namespace
            )
            return SeedResult(
                user_id=user.id,
                username=username,
                password=password,
                workspace_id=workspace.id,
                environment_revision_id=environment_revision_id,
                namespace=namespace,
            )
        finally:
            await runtime.aclose()

    async def _seed_environment(
        self, runtime: PlatformRuntime, *, workspace_id: UUID, principal_id: UUID, namespace: str
    ) -> UUID:
        application_id = uuid4()
        revision_id = uuid4()
        content = {
            "target_base_url": f"{self.taskboard_base_url}/{namespace}",
            "fixture_ref": "taskboard@1",
            "namespace": namespace,
            "parameters": {"item_name": ITEM_NAME},
        }
        engine = runtime.engines[ROLE_API]
        factory = create_session_factory(engine)
        async with factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            await session.execute(
                sa.insert(tables.applications).values(
                    id=application_id, workspace_id=workspace_id, slug=f"app-{application_id.hex[:8]}", name="UI app"
                )
            )
            await session.execute(
                sa.insert(tables.environment_revisions).values(
                    id=revision_id,
                    workspace_id=workspace_id,
                    application_id=application_id,
                    revision_no=1,
                    content=content,
                    content_digest=digest_content(content),
                    lifecycle="ready",
                    author="ui-harness",
                )
            )
        return revision_id

    def _start_api(self) -> None:
        assert self.seed is not None
        assert self.supervisor is not None
        os.environ["AGENTQA_SUPERVISOR_HOST"] = "127.0.0.1"
        os.environ["AGENTQA_SUPERVISOR_PORT"] = str(self.supervisor.port)
        os.environ["AGENTQA_SUPERVISOR_TOKEN"] = self.supervisor.token
        dist = REPO_ROOT / "apps" / "web" / "dist"
        if (dist / "index.html").is_file():
            os.environ["AGENTQA_WEB_DIST"] = str(dist)
        runtime = PlatformRuntime.build(
            profile=RuntimeProfile.local(),
            dsn_by_role={ROLE_API: self.dsn_by_role[ROLE_API], ROLE_WORKER: self.dsn_by_role[ROLE_WORKER]},
            artifact_store=FileSystemBlobStore(self.workspace_root / "blobs"),
            taint=TaintRegistry(),
            generative_model=HarnessAuthoringGo(),
        )
        self.runtime = runtime
        app = create_application(runtime)
        port = free_port()
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self.api_server = uvicorn.Server(config)

        def thread_main() -> None:
            loop: asyncio.AbstractEventLoop = (
                asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
            )
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.api_server.serve())
            finally:
                loop.close()

        self.api_thread = threading.Thread(target=thread_main, name="ui-e2e-api", daemon=True)
        self.api_thread.start()
        self.api_base_url = f"http://127.0.0.1:{port}"
        wait_for_http(f"{self.api_base_url}/health/live")

    def _start_web(self) -> None:
        if self.build_web:
            self.log("building web app")
            subprocess.run(
                ["pnpm", "--dir", "apps/web", "build"],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                shell=sys.platform == "win32",
            )
        dist = REPO_ROOT / "apps" / "web" / "dist"
        if (dist / "index.html").is_file():
            self.web_base_url = self.api_base_url
            self.log("web served same-origin from api")
            return
        port = free_port()
        environment = {**sanitized_environment(), "AGENTQA_API_TARGET": self.api_base_url}
        self.web_process = subprocess.Popen(
            [
                "pnpm",
                "--dir",
                "apps/web",
                "exec",
                "vite",
                "preview",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--strictPort",
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            shell=sys.platform == "win32",
        )
        self.web_base_url = f"http://127.0.0.1:{port}"
        wait_for_http(self.web_base_url, timeout=90)

    def _start_worker(self) -> None:
        assert self.seed is not None
        assert self.supervisor is not None

        def thread_main() -> None:
            _run_db(self._worker_loop())

        self.worker_thread = threading.Thread(target=thread_main, name="ui-e2e-worker", daemon=True)
        self.worker_thread.start()

    def pause_worker(self) -> None:
        self.worker_stop.set()
        if self.worker_thread is not None:
            self.worker_thread.join(timeout=15)
        self.worker_thread = None

    def resume_worker(self) -> None:
        if self.worker_thread is not None and self.worker_thread.is_alive():
            return
        self.worker_stop.clear()
        self._start_worker()

    def seed_ready_case(
        self, *, logical_key: str = "live_case", item_name: str = ITEM_NAME, settle_seconds: int = 2
    ) -> UUID:
        assert self.seed is not None
        from tools.ui_harness.authoring_model import authored_taskboard_case

        payload = {"goal": "Tạo việc mới", "requirement_keys": ["create_item"], "sources": []}
        payload["settle_seconds"] = settle_seconds
        document = authored_taskboard_case(payload)
        document["logical_key"] = logical_key
        document["requirements"] = ["create_item"]
        return self.seed_case_document(logical_key=logical_key, document=document)

    def seed_viewer(self, *, prefix: str = "ui-viewer") -> tuple[str, str]:
        assert self.seed is not None
        username = f"{prefix}-{secrets.token_hex(4)}"
        password = "pw-viewer-123456"

        async def seed() -> None:
            runtime = PlatformRuntime.build(
                profile=RuntimeProfile.local(),
                dsn_by_role={ROLE_API: self.dsn_by_role[ROLE_API], ROLE_WORKER: self.dsn_by_role[ROLE_WORKER]},
                artifact_store=FileSystemBlobStore(self.workspace_root / "blobs"),
            )
            try:
                from agentqa.platform.identity.models import Role

                user = await runtime.users.create(username=username, password=password)
                await runtime.authorization.add_membership(
                    workspace_id=self.seed.workspace_id,
                    actor_id=self.seed.user_id,
                    user_id=user.id,
                    role=Role.VIEWER,
                )
            finally:
                await runtime.aclose()

        _run_db(seed())
        return username, password

    def seed_case_document(self, *, logical_key: str, document: dict) -> UUID:
        assert self.seed is not None

        async def promote() -> UUID:
            runtime = PlatformRuntime.build(
                profile=RuntimeProfile.local(),
                dsn_by_role={ROLE_API: self.dsn_by_role[ROLE_API], ROLE_WORKER: self.dsn_by_role[ROLE_WORKER]},
                artifact_store=FileSystemBlobStore(self.workspace_root / "blobs"),
                taint=TaintRegistry(),
                generative_model=HarnessAuthoringGo(),
            )
            try:
                entity = await runtime.revisions.create_entity(
                    workspace_id=self.seed.workspace_id,
                    principal_id=self.seed.user_id,
                    kind="case",
                    logical_key=logical_key,
                )
                receipt = await runtime.revisions.promote_content(
                    workspace_id=self.seed.workspace_id,
                    principal_id=self.seed.user_id,
                    actor="ui-harness",
                    kind="case",
                    entity_id=entity.id,
                    content=document,
                )
                return receipt.revision_id
            finally:
                await runtime.aclose()

        return _run_db(promote())

    def case_draft_version(self, case_id: UUID) -> int | None:
        assert self.seed is not None

        async def query() -> int | None:
            engine = create_async_engine(self.dsn_by_role[ROLE_API])
            try:
                factory = create_session_factory(engine)
                async with factory() as session, session.begin():
                    await set_scope(session, principal_id=self.seed.user_id, workspace_id=self.seed.workspace_id)
                    row = (
                        await session.execute(
                            sa.select(tables.case_drafts.c.edit_version).where(
                                tables.case_drafts.c.workspace_id == self.seed.workspace_id,
                                tables.case_drafts.c.case_id == case_id,
                            )
                        )
                    ).one_or_none()
                    return row.edit_version if row is not None else None
            finally:
                await engine.dispose()

        return _run_db(query())

    def seed_experiment_revision(self, *, logical_key: str, content: dict) -> str:
        assert self.seed is not None

        async def create() -> str:
            from agentqa.platform.experiments import ExperimentService

            engine = create_async_engine(self.dsn_by_role[ROLE_API])
            try:
                service = ExperimentService(engine)
                view = await service.create_revision(
                    workspace_id=self.seed.workspace_id,
                    principal_id=self.seed.user_id,
                    actor="ui-harness",
                    logical_key=logical_key,
                    content=content,
                )
                return str(view.revision_id)
            finally:
                await engine.dispose()

        return _run_db(create())

    def execute_experiment(self, revision_id: str) -> dict[str, Any]:
        assert self.seed is not None
        harness = self

        class _HarnessSlotRunner:
            async def run_slot(self, slot, arm_payload: dict[str, Any]) -> dict[str, Any]:
                if arm_payload.get("baseline") and harness.seeded_case_revision is not None:
                    run_id = await asyncio.to_thread(harness.run_replay, harness.seeded_case_revision)
                    state = await asyncio.to_thread(harness.wait_for_run, run_id)
                    return {
                        "status": "completed",
                        "run_id": str(run_id),
                        "product": {"verdict": state.get("verdict"), "gate": state.get("gate")},
                        "oracle": {
                            "task_outcome": "unscorable",
                            "unscorable_reason": "no_oracle_record",
                            "counters": {},
                        },
                        "gate": {"result": state.get("gate")},
                        "usage": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "wall_time_seconds": 0.0},
                    }
                return {"status": "blocked", "blocked_reason": "runner_unavailable"}

        async def execute() -> dict[str, Any]:
            from agentqa.platform.experiments import ExperimentService

            engine = create_async_engine(self.dsn_by_role[ROLE_API])
            try:
                service = ExperimentService(engine)
                return await service.execute(
                    workspace_id=self.seed.workspace_id,
                    principal_id=self.seed.user_id,
                    revision_id=UUID(revision_id),
                    slot_runner=_HarnessSlotRunner(),
                )
            finally:
                await engine.dispose()

        return _run_db(execute())

    async def _worker_loop(self) -> None:
        assert self.seed is not None
        assert self.supervisor is not None
        engine: AsyncEngine = create_async_engine(self.dsn_by_role[ROLE_WORKER])
        try:
            queue = JobQueue(
                create_session_factory(engine),
                workspace_id=self.seed.workspace_id,
                principal_id=self.seed.user_id,
                slot_capacity=4,
            )
            coordinator = RemoteCoordinator(self.supervisor)
            recorder = RunEventRecorder(engine)
            worker = HarnessWorker(
                healing_profile=self.healing_profile,
                queue=queue,
                coordinator=coordinator,
                recorder=recorder,
                engine=engine,
                principal_id=self.seed.user_id,
                workspace_id=self.seed.workspace_id,
                worker_id="ui-e2e-worker",
            )
            while not self.worker_stop.is_set():
                try:
                    await worker.run_until_idle()
                except Exception as error:
                    self.worker_errors.append(str(error))
                await asyncio.sleep(0.5)
        finally:
            await engine.dispose()

    def wait_for_run(self, run_id: UUID, *, timeout: float = 180.0) -> dict[str, Any]:
        assert self.seed is not None

        async def poll() -> dict[str, Any]:
            engine = create_async_engine(self.dsn_by_role[ROLE_API])
            try:
                factory = create_session_factory(engine)
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    async with factory() as session, session.begin():
                        await set_scope(session, principal_id=self.seed.user_id, workspace_id=self.seed.workspace_id)
                        row = (await session.execute(sa.select(tables.runs).where(tables.runs.c.id == run_id))).one()
                    if row.status in ("succeeded", "failed", "cancelled", "inconclusive", "error"):
                        return {
                            "status": row.status,
                            "verdict": row.verdict,
                            "gate": row.gate,
                            "reasons": list(row.reasons or []),
                        }
                    await asyncio.sleep(0.5)
                raise HarnessError(f"run {run_id} không kết thúc trong {timeout}s")
            finally:
                await engine.dispose()

        return _run_db(poll())

    def find_run_by_prefix(self, prefix: str) -> UUID | None:
        assert self.seed is not None

        async def query() -> UUID | None:
            engine = create_async_engine(self.dsn_by_role[ROLE_API])
            try:
                factory = create_session_factory(engine)
                async with factory() as session, session.begin():
                    await set_scope(session, principal_id=self.seed.user_id, workspace_id=self.seed.workspace_id)
                    row = (
                        await session.execute(
                            sa.select(tables.runs.c.id).where(
                                tables.runs.c.workspace_id == self.seed.workspace_id,
                                sa.cast(tables.runs.c.id, sa.Text).like(f"{prefix}%"),
                            )
                        )
                    ).one_or_none()
                    return row.id if row is not None else None
            finally:
                await engine.dispose()

        return _run_db(query())

    def ready_case_revision_count(self, logical_key: str) -> int:
        assert self.seed is not None

        async def query() -> int:
            engine = create_async_engine(self.dsn_by_role[ROLE_API])
            try:
                factory = create_session_factory(engine)
                async with factory() as session, session.begin():
                    await set_scope(session, principal_id=self.seed.user_id, workspace_id=self.seed.workspace_id)
                    return (
                        await session.execute(
                            sa.select(sa.func.count())
                            .select_from(tables.case_revisions)
                            .join(
                                tables.cases,
                                (tables.cases.c.workspace_id == tables.case_revisions.c.workspace_id)
                                & (tables.cases.c.id == tables.case_revisions.c.case_id),
                            )
                            .where(
                                tables.case_revisions.c.workspace_id == self.seed.workspace_id,
                                tables.cases.c.logical_key == logical_key,
                                tables.case_revisions.c.lifecycle == "ready",
                            )
                        )
                    ).scalar_one()
            finally:
                await engine.dispose()

        return _run_db(query())

    def bump_draft_from_api(self, case_id: UUID, edit_version: int) -> None:
        assert self.seed is not None

        async def bump() -> None:
            engine = create_async_engine(self.dsn_by_role[ROLE_API])
            try:
                factory = create_session_factory(engine)
                async with factory() as session, session.begin():
                    await set_scope(session, principal_id=self.seed.user_id, workspace_id=self.seed.workspace_id)
                    draft = (
                        await session.execute(
                            sa.select(tables.case_drafts).where(
                                tables.case_drafts.c.workspace_id == self.seed.workspace_id,
                                tables.case_drafts.c.case_id == case_id,
                            )
                        )
                    ).one()
                    if draft.edit_version != edit_version:
                        raise HarnessError("edit_version không khớp khi bump draft")
                    content = dict(draft.content)
                    content["title"] = "Bản server đổi tiêu đề"
                    await session.execute(
                        sa.update(tables.case_drafts)
                        .where(
                            tables.case_drafts.c.workspace_id == self.seed.workspace_id,
                            tables.case_drafts.c.case_id == case_id,
                        )
                        .values(edit_version=edit_version + 1, content=content, updated_by="ui-harness")
                    )
            finally:
                await engine.dispose()

        _run_db(bump())

    def latest_case_revision(self, logical_key: str) -> tuple[UUID, UUID]:
        assert self.seed is not None

        async def query() -> tuple[UUID, UUID]:
            engine = create_async_engine(self.dsn_by_role[ROLE_API])
            try:
                factory = create_session_factory(engine)
                async with factory() as session, session.begin():
                    await set_scope(session, principal_id=self.seed.user_id, workspace_id=self.seed.workspace_id)
                    row = (
                        await session.execute(
                            sa.select(tables.case_revisions.c.id, tables.case_revisions.c.case_id)
                            .join(
                                tables.cases,
                                (tables.cases.c.workspace_id == tables.case_revisions.c.workspace_id)
                                & (tables.cases.c.id == tables.case_revisions.c.case_id),
                            )
                            .where(
                                tables.case_revisions.c.workspace_id == self.seed.workspace_id,
                                tables.cases.c.logical_key == logical_key,
                                tables.case_revisions.c.lifecycle == "ready",
                            )
                            .order_by(tables.case_revisions.c.revision_no.desc())
                            .limit(1)
                        )
                    ).one_or_none()
                    if row is None:
                        raise HarnessError(f"không tìm thấy ready revision cho {logical_key}")
                    return row.id, row.case_id
            finally:
                await engine.dispose()

        return _run_db(query())

    def peek_run(self, run_id: UUID) -> dict[str, Any]:
        assert self.seed is not None

        async def query() -> dict[str, Any]:
            engine = create_async_engine(self.dsn_by_role[ROLE_API])
            try:
                factory = create_session_factory(engine)
                async with factory() as session, session.begin():
                    await set_scope(session, principal_id=self.seed.user_id, workspace_id=self.seed.workspace_id)
                    row = (await session.execute(sa.select(tables.runs).where(tables.runs.c.id == run_id))).one()
                return {
                    "status": row.status,
                    "verdict": row.verdict,
                    "gate": row.gate,
                    "reasons": list(row.reasons or []),
                }
            finally:
                await engine.dispose()

        return _run_db(query())

    def run_replay(self, case_revision_id: UUID, *, policy: str = "default", gate_profile: str = "strict") -> UUID:
        assert self.seed is not None

        async def submit() -> UUID:
            engine = create_async_engine(self.dsn_by_role[ROLE_API])
            try:
                service = RunService(engine)
                outcome = await service.submit(
                    SubmitRequest(
                        workspace_id=self.seed.workspace_id,
                        principal_id=self.seed.user_id,
                        actor="ui-e2e",
                        idempotency_key=uuid4().hex,
                        case_revision_ids=(case_revision_id,),
                        environment_revision_id=self.seed.environment_revision_id,
                        provided_capabilities=frozenset(),
                        policy=policy,
                        gate_profile=gate_profile,
                    )
                )
                return outcome.run_id
            finally:
                await engine.dispose()

        return _run_db(submit())

    def run_events(self, run_id: UUID) -> list[dict[str, Any]]:
        assert self.seed is not None

        async def query() -> list[dict[str, Any]]:
            engine = create_async_engine(self.dsn_by_role[ROLE_API])
            try:
                events = EventService(engine)
                return await events.query_durable(
                    workspace_id=self.seed.workspace_id,
                    principal_id=self.seed.user_id,
                    run_id=run_id,
                    limit=500,
                )
            finally:
                await engine.dispose()

        return _run_db(query())

    def logout_api(self) -> None:
        assert self.seed is not None
        with httpx.Client(base_url=self.api_base_url, headers={"Origin": self.api_base_url}) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"username": self.seed.username, "password": self.seed.password},
            )
            login.raise_for_status()
            csrf = login.json()["csrf_token"]
            logout = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
            if logout.status_code not in (204, 200):
                raise HarnessError(f"logout thất bại: {logout.status_code} {logout.text}")

    def revoke_session(self, raw_token: str) -> None:
        assert self.seed is not None

        async def revoke() -> None:
            from agentqa.platform.identity.sessions import SessionService

            engine = create_async_engine(self.dsn_by_role[ROLE_API])
            try:
                await SessionService(engine).logout(raw_token)
            finally:
                await engine.dispose()

        _run_db(revoke())

    def workspace_requires_auth(self) -> bool:
        assert self.seed is not None
        with httpx.Client(base_url=self.api_base_url, headers={"Origin": self.api_base_url}) as client:
            response = client.get(f"/api/v1/workspaces/{self.seed.workspace_id}/runs")
        return response.status_code == 401

    def stop(self) -> None:
        self.worker_stop.set()
        if self.worker_thread is not None:
            self.worker_thread.join(timeout=15)
        if self.web_process is not None and self.web_process.poll() is None:
            self.web_process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.web_process.wait(timeout=10)
        if self.api_server is not None:
            self.api_server.should_exit = True
        if self.api_thread is not None:
            self.api_thread.join(timeout=15)
        if self.supervisor is not None:
            self.supervisor.terminate()
        if self.taskboard_server is not None:
            self.taskboard_server.should_exit = True
        if self.taskboard_thread is not None:
            self.taskboard_thread.join(timeout=10)
        if self.runtime is not None:
            with contextlib.suppress(Exception):
                _run_db(self.runtime.aclose())
        with contextlib.suppress(Exception):
            _run_db(drop_database(admin_dsn(), self.db_name))
        (self.workspace_root / "harness.log").write_text("\n".join(self.log_lines), encoding="utf-8")


def probe_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        if event["type"] == "fixture.probed":
            return event["summary"].get("probe", {})
    return {}


def run_scenario(*, scenario: str = "authoring", build_web: bool = True) -> HarnessReport:
    harness = UiHarness(scenario=scenario, build_web=build_web)
    report = HarnessReport(ok=False)
    os.environ["AGENTQA_LLM_API_KEY"] = CANARY_KEY
    if scenario in ("healing", "reporting"):
        from tests.support.healing import synthetic_profile

        harness.healing_profile = synthetic_profile()
    try:
        harness.start()
        report.workspace_id = str(harness.seed.workspace_id) if harness.seed else ""
        try:
            if scenario == "authoring":
                from tools.ui_harness.scenario_authoring import drive_authoring_flow

                checks, draft_run, replay_run = _run_async(drive_authoring_flow(harness))
            elif scenario == "healing":
                from tools.ui_harness.scenario_healing import drive_healing_flow

                checks, _runs = _run_async(drive_healing_flow(harness))
                draft_run = {}
                replay_run = None
            elif scenario == "reporting":
                from tools.ui_harness.scenario_reporting import drive_reporting_flow

                checks, _runs = _run_async(drive_reporting_flow(harness))
                draft_run = {}
                replay_run = None
            elif scenario == "admin":
                from tools.ui_harness.scenario_admin import drive_admin_flow

                checks, _runs = _run_async(drive_admin_flow(harness))
                draft_run = {}
                replay_run = None
            elif scenario == "experiments":
                from tools.ui_harness.scenario_experiments import drive_experiments_flow

                checks, _runs = _run_async(drive_experiments_flow(harness))
                draft_run = {}
                replay_run = None
            else:
                from tools.ui_harness.scenario_live import drive_live_flow

                checks, _runs = _run_async(drive_live_flow(harness))
                draft_run = {}
                replay_run = None
        except Exception as error:
            report.error = str(error)
            report.checks.append(HarnessCheck(name="scenario", ok=False, detail=str(error)))
            (harness.workspace_root / "report.json").write_text(
                json.dumps({"error": str(error), "logs": harness.log_lines}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return report
        report.checks.extend(checks)
        report.draft_run_verdict = draft_run.get("verdict") if draft_run else None
        if replay_run is not None:
            report.run_id = str(replay_run.get("run_id", ""))
            report.run_verdict = replay_run.get("state", {}).get("verdict")
        report.artifacts_dir = str(harness.workspace_root)
        report.ok = all(check.ok for check in report.checks) and report.error is None
        return report
    except Exception as error:
        if report.error is None:
            report.error = str(error)
        report.ok = False
        return report
    finally:
        harness.stop()
        os.environ.pop("AGENTQA_LLM_API_KEY", None)


def _run_async(coro: Any) -> Any:
    if sys.platform == "win32":
        loop: asyncio.AbstractEventLoop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
