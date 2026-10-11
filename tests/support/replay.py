from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from agentqa.contracts.canonical import digest_content
from agentqa.contracts.case import CaseContent
from agentqa.contracts.observation import Modality
from agentqa.platform.fixtures import TaskboardFixture
from agentqa.platform.queue import JobQueue
from agentqa.platform.runs.coordinator import ExecutionOutcome, ExecutionSpec, RunEventRecorder, outcome_from_dict
from agentqa.platform.runs.service import RunService, SubmitRequest
from agentqa.platform.runs.worker import RunWorker
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.roles import ROLE_API, ROLE_SUPERVISOR, ROLE_WORKER
from agentqa.platform.storage.scope import set_scope
from agentqa.platform.supervisor import CommandJournal
from tests.support.faults import SupervisorProcess, start_supervisor
from tests.support.postgres import seed_attempt, seed_workspace
from tests.support.taskboard import TaskboardServer


@dataclass
class ReplaySupervisor:
    process: SupervisorProcess

    def run_execution(self, spec: ExecutionSpec) -> dict[str, Any]:
        client = self.process.client()
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
        assert response.get("ok") is True, response
        return response["result"]

    def apply_control(self, control_id: UUID) -> dict[str, Any]:
        client = self.process.client()
        try:
            response = client.request({"op": "apply_control", "control_id": str(control_id)})
        finally:
            client.close_socket()
        assert response.get("ok") is True, response
        return response["result"]

    def terminate(self) -> None:
        self.process.terminate()


class RemoteCoordinator:
    def __init__(self, supervisor: ReplaySupervisor) -> None:
        self._supervisor = supervisor

    async def execute(self, spec: ExecutionSpec) -> ExecutionOutcome:
        result = await asyncio.to_thread(self._supervisor.run_execution, spec)
        return outcome_from_dict(result)

    async def apply_control(self, control_id: UUID) -> dict[str, Any]:
        return await asyncio.to_thread(self._supervisor.apply_control, control_id)


@dataclass
class ReplayHarness:
    supervisor: ReplaySupervisor
    fixtures: TaskboardFixture
    worker: RunWorker
    journal: CommandJournal
    queue: JobQueue

    def aclose(self) -> None:
        self.supervisor.terminate()


def start_replay_supervisor(
    *,
    dsn: str,
    workspace_id: UUID,
    principal_id: UUID,
    run_id: UUID,
    attempt_id: UUID,
    taskboard_server: TaskboardServer,
    fence_epoch: int = 1,
    lease_seconds: float = 300.0,
    fault_loss_intent: str = "",
    fault_storage: bool = False,
    agent_models: bool = False,
    agent_script: str = "",
    fixture_endpoints: list[str] | None = None,
    baseline_dir: str = "",
    extra_allow_origins: list[str] | None = None,
) -> ReplaySupervisor:
    parts = urlsplit(taskboard_server.base_url)
    extra_args = [
        f"--fixture-base-url={taskboard_server.base_url}",
        f"--fixture-control-token={taskboard_server.control_token}",
    ]

    if fault_loss_intent:
        extra_args.append(f"--fault-loss-intent={fault_loss_intent}")
    if fault_storage:
        extra_args.append("--fault-storage")
    if agent_models:
        extra_args.append("--agent-models=fake")
    if agent_script:
        extra_args.append(f"--agent-script={agent_script}")
    for endpoint in fixture_endpoints or []:
        extra_args.append(f"--fixture-endpoint={endpoint}")
    if baseline_dir:
        extra_args.append(f"--baseline-dir={baseline_dir}")
    process = start_supervisor(
        dsn=dsn,
        workspace_id=workspace_id,
        principal_id=principal_id,
        run_id=run_id,
        attempt_id=attempt_id,
        session_key=f"replay-{execution_key(run_id)}",
        allow_origins=[f"127.0.0.1:{parts.port}", *(extra_allow_origins or [])],
        lease_seconds=lease_seconds,
        fence_epoch=fence_epoch,
        supervisor_id="replay-sup",
        extra_args=extra_args,
    )
    return ReplaySupervisor(process=process)


def execution_key(run_id: UUID) -> str:
    return str(run_id)[:8]


class HealingWorker(RunWorker):
    def __init__(self, *, healing_profile, **kwargs) -> None:
        super().__init__(**kwargs)
        self._healing_profile = healing_profile

    async def _load(self, execution_id: UUID) -> ExecutionSpec:
        spec = await super()._load(execution_id)
        if self._healing_profile is None:
            return spec
        return dataclasses.replace(spec, healing_profile=self._healing_profile)


def build_replay_harness(
    *,
    engines: dict,
    test_db,
    principal_id: UUID,
    workspace_id: UUID,
    taskboard_server: TaskboardServer,
    fault_loss_intent: str = "",
    fault_storage: bool = False,
    agent_models: bool = False,
    agent_script: str = "",
    healing_profile=None,
    fixture_endpoints: list[str] | None = None,
    baseline_dir: str = "",
    extra_allow_origins: list[str] | None = None,
) -> ReplayHarness:
    supervisor = start_replay_supervisor(
        dsn=test_db.dsn(ROLE_SUPERVISOR),
        workspace_id=workspace_id,
        principal_id=principal_id,
        run_id=UUID(int=0),
        attempt_id=UUID(int=0),
        taskboard_server=taskboard_server,
        fault_loss_intent=fault_loss_intent,
        fault_storage=fault_storage,
        agent_models=agent_models,
        agent_script=agent_script,
        fixture_endpoints=fixture_endpoints,
        baseline_dir=baseline_dir,
        extra_allow_origins=extra_allow_origins,
    )
    remote = RemoteCoordinator(supervisor)
    recorder = RunEventRecorder(engines[ROLE_WORKER])
    queue = JobQueue(
        create_session_factory(engines[ROLE_WORKER]),
        workspace_id=workspace_id,
        principal_id=principal_id,
        slot_capacity=4,
    )
    worker: RunWorker
    if healing_profile is None:
        worker = RunWorker(
            queue=queue,
            coordinator=remote,
            recorder=recorder,
            engine=engines[ROLE_WORKER],
            principal_id=principal_id,
            workspace_id=workspace_id,
        )
    else:
        worker = HealingWorker(
            healing_profile=healing_profile,
            queue=queue,
            coordinator=remote,
            recorder=recorder,
            engine=engines[ROLE_WORKER],
            principal_id=principal_id,
            workspace_id=workspace_id,
        )
    journal = CommandJournal(
        create_session_factory(engines[ROLE_SUPERVISOR]),
        workspace_id=workspace_id,
        principal_id=principal_id,
        supervisor_id="replay-sup",
    )
    fixtures = TaskboardFixture(taskboard_server.base_url, taskboard_server.control_token)
    return ReplayHarness(
        supervisor=supervisor,
        fixtures=fixtures,
        worker=worker,
        journal=journal,
        queue=queue,
    )


async def seed_replay_workspace(engines: dict) -> tuple[UUID, UUID]:
    from uuid import uuid4

    return await seed_workspace(engines, label=f"replay-{uuid4().hex[:8]}")


async def seed_environment_revision(engines: dict, *, principal_id: UUID, workspace_id: UUID, content: dict) -> UUID:
    from uuid import uuid4

    application_id = uuid4()
    revision_id = uuid4()
    async with create_session_factory(engines[ROLE_API])() as session, session.begin():
        await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
        await session.execute(
            tables.applications.insert().values(
                id=application_id, workspace_id=workspace_id, slug=f"app-{application_id.hex[:8]}", name="fixture"
            )
        )
        await session.execute(
            tables.environment_revisions.insert().values(
                id=revision_id,
                workspace_id=workspace_id,
                application_id=application_id,
                revision_no=1,
                content=content,
                content_digest=digest_content(content),
                lifecycle="ready",
                author="tester",
            )
        )
    return revision_id


async def submit_case_run(
    engines: dict,
    *,
    principal_id: UUID,
    workspace_id: UUID,
    case: CaseContent | None = None,
    cases: tuple[CaseContent, ...] | None = None,
    environment_content: dict,
    idempotency_key: str | None = None,
    policy: str = "default",
    observation_mode: str = "semantic",
    gate_profile: str = "default",
) -> dict:
    from uuid import uuid4

    from tests.support.postgres import seed_case_revision

    case_list = tuple(cases) if cases is not None else (case,)
    revision_ids = []
    case_id = None
    for index, item in enumerate(case_list):
        if item is None:
            raise ValueError("case không được None")
        case_id, revision_id = await seed_case_revision(
            engines,
            principal_id=principal_id,
            workspace_id=workspace_id,
            logical_key=f"{item.logical_key}-{index}-{uuid4().hex[:6]}",
            content=item.model_dump(mode="json"),
            content_digest=digest_content(item),
        )
        revision_ids.append(revision_id)
    environment_id = await seed_environment_revision(
        engines, principal_id=principal_id, workspace_id=workspace_id, content=environment_content
    )
    service = RunService(engines[ROLE_API])
    outcome = await service.submit(
        SubmitRequest(
            workspace_id=workspace_id,
            principal_id=principal_id,
            actor="tester",
            idempotency_key=idempotency_key or uuid4().hex,
            case_revision_ids=tuple(revision_ids),
            environment_revision_id=environment_id,
            provided_capabilities=frozenset(),
            policy=policy,
            observation_mode=Modality(observation_mode),
            gate_profile=gate_profile,
        )
    )
    async with create_session_factory(engines[ROLE_API])() as session, session.begin():
        await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
        execution_ids = [
            row.id
            for row in (
                await session.execute(
                    tables.executions.select()
                    .where(tables.executions.c.run_id == outcome.run_id)
                    .order_by(tables.executions.c.created_at, tables.executions.c.id)
                )
            ).all()
        ]
    attempt_ids = []
    for execution_id in execution_ids:
        attempt_ids.append(
            await seed_attempt(
                engines,
                principal_id=principal_id,
                workspace_id=workspace_id,
                execution_id=execution_id,
                fence_epoch=1,
            )
        )
    return {
        "run_id": outcome.run_id,
        "execution_id": execution_ids[0],
        "execution_ids": execution_ids,
        "attempt_id": attempt_ids[0],
        "attempt_ids": attempt_ids,
        "case_id": case_id,
        "case_revision_id": revision_ids[0],
        "environment_revision_id": environment_id,
        "snapshot_digest": outcome.snapshot_digest,
    }
