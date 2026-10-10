from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin
from uuid import UUID, uuid4

from agentqa.agent.browser import PlaywrightReadPort
from agentqa.agent.browser.contexts import ContextRegistry
from agentqa.agent.healing import HealContext, Healer, build_healer
from agentqa.agent.identity import TargetGuard
from agentqa.agent.replay import PlaywrightSceneProvider, ReplayRunner, validate_case
from agentqa.agent.replay.runner import ActionOutcomeView
from agentqa.contracts.calibration import CalibrationProfile
from agentqa.contracts.case import ActionNode, CaseContent, CheckpointNode
from agentqa.contracts.errors import AgentQAValidationError
from agentqa.contracts.healing import HealingActor, HealingDecision, HealingRecord
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.observation import Modality, Observation, RedactionStatus
from agentqa.contracts.policies import PolicyKind, RunMode, validate_mode_policy_modality
from agentqa.contracts.runs import ExecutionStatus
from agentqa.contracts.values import LiteralValue
from agentqa.contracts.verification import (
    AssertionResult,
    AssertionStatus,
    CheckpointEvaluationRequest,
    EvidenceStatus,
)
from agentqa.platform.fixtures import FixtureRegistry
from agentqa.platform.runs.composition import (
    AgentModels,
    bundle_from_replay,
    run_agent_bundle,
)
from agentqa.platform.runs.facts import capture_facts
from agentqa.platform.supervisor.commands import CommandRequest
from agentqa.platform.supervisor.runtime import SupervisorRuntime
from agentqa.verify import (
    AttemptEvidence,
    CompletionOutcome,
    CompletionPlan,
    ExecutionProof,
    GateContext,
    assertion_applicability,
    evaluate_completion,
    evaluate_gate,
    reduce_verdict,
)
from agentqa.verify.evaluators import evaluate_assertion, evaluate_checkpoint

AGENT_POLICIES = frozenset({PolicyKind.LLM.value, PolicyKind.JEV_CASCADE.value})


@dataclass(frozen=True)
class ExecutionSpec:
    workspace_id: UUID
    principal_id: UUID
    run_id: UUID
    execution_id: UUID
    attempt_id: UUID
    logical_key: str
    case: CaseContent
    target_base_url: str
    fixture_ref: str
    namespace: str
    parameters: dict[str, str] = field(default_factory=dict)
    gate_profile: str = "strict"
    fence_epoch: int = 1
    actor: str = "worker"
    policy: str = "replay"
    observation_mode: str = "semantic"
    snapshot_digest: str = ""
    provisional: bool = False
    healing_profile: CalibrationProfile | None = None
    case_id: UUID | None = None
    case_revision_id: UUID | None = None


@dataclass
class ExecutionOutcome:
    execution_id: UUID
    status: str
    verdict: str | None
    gate: str | None
    gate_reasons: list[str]
    reasons: list[str]
    capability: dict[str, Any]
    steps: list[dict[str, Any]]
    assertion_results: list[AssertionResult]
    completion: CompletionOutcome
    trace_refs: list[str]
    unknown_commands: list[str]
    cleanup_failed: bool = False
    outcome_probe: dict[str, Any] | None = None
    degraded: bool = False
    policy_versions: list[str] = field(default_factory=list)
    healing_records: list[HealingRecord] = field(default_factory=list)


class BridgedRunEventRecorder:
    def __init__(self, bridge: Any, dsn: str) -> None:
        self._bridge = bridge
        self._dsn = dsn
        self._inner: RunEventRecorder | None = None

    async def _ensure(self) -> RunEventRecorder:
        if self._inner is None:
            dsn = self._dsn
            self._inner = await self._bridge.call_factory(lambda: _build_recorder(dsn))
        assert self._inner is not None
        return self._inner

    async def record(self, **kwargs: Any) -> None:
        inner = await self._ensure()
        await self._bridge.call_factory(lambda: inner.record(**kwargs))


async def _build_recorder(dsn: str) -> RunEventRecorder:
    from agentqa.platform.storage.database import create_engine

    return RunEventRecorder(create_engine(dsn))


class RunEventRecorder:
    def __init__(self, engine) -> None:
        from agentqa.platform.events.service import EventService
        from agentqa.platform.storage.database import create_session_factory
        from agentqa.platform.storage.scope import set_scope

        self._events = EventService(engine)
        self._factory = create_session_factory(engine)
        self._set_scope = set_scope

    async def record(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        run_id: UUID,
        event_type: str,
        actor: str,
        payload: dict[str, Any] | None = None,
        execution_id: UUID | None = None,
    ) -> None:
        async with self._factory() as session, session.begin():
            await self._set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            await self._events.append(
                session,
                workspace_id=workspace_id,
                run_id=run_id,
                event_type=event_type,
                actor=actor,
                payload=payload or {},
                execution_id=execution_id,
            )


class _CoordinatorHooks:
    def __init__(
        self,
        coordinator: RunCoordinator,
        spec: ExecutionSpec,
        session_key: str,
        context_key: str,
    ) -> None:
        self._coordinator = coordinator
        self._spec = spec
        self._session_key = session_key
        self._context_key = context_key
        self.unknown_commands: list[str] = []
        self.storage_failures: list[str] = []
        self.evidence_statuses: dict[str, EvidenceStatus] = {}
        self.healing_records: list[HealingRecord] = []
        self.captures: dict[str, object] = {}

    async def current_scene_version(self) -> int:
        view = await self._coordinator.runtime.session_view(self._session_key)
        return int(view["scene_version"]) if view else 1

    async def sync_captures(self, captures: dict[str, object]) -> None:
        self.captures = dict(captures)

    async def probe_condition(self, condition) -> bool | None:
        try:
            probe = await self._coordinator.read_port.probe(condition, self._context_key)
        except Exception:
            self.storage_failures.append("probe_condition")
            return None
        if probe.error_code is not None:
            return None
        return bool(probe.satisfied)

    async def capture_probe(self, probe) -> tuple[bool, str | None]:
        from agentqa.contracts.verification import AssertionSpec, AssertionStatus, Comparator

        spec = AssertionSpec(
            id="capture",
            comparator=probe.comparator,
            target=probe.target,
            expected=probe.expected,
        )
        facts = await capture_facts(
            self._coordinator.contexts,
            self._context_key,
            [spec],
            {},
            captures=self.captures,
            parameters=dict(self._spec.parameters),
            read_port=self._coordinator.read_port,
        )
        outcome = evaluate_assertion(spec, facts)
        satisfied = outcome.status == AssertionStatus.PASSED
        observed = outcome.observed
        if probe.target is not None:
            if probe.comparator in (
                Comparator.COUNT_EQUALS,
                Comparator.COUNT_GREATER_OR_EQUAL,
                Comparator.UNIQUE,
                Comparator.EXISTS,
                Comparator.ABSENT,
            ):
                observed = str(facts.count(probe.target))
            elif probe.comparator in (Comparator.VISIBLE, Comparator.HIDDEN):
                observed = str(facts.visible(probe.target))
        return satisfied, observed

    async def scene(self):
        return await self._coordinator.scene_provider.scene(self._context_key)

    async def record_healing(self, record: HealingRecord) -> None:
        if record.proposal is not None and record.proposal.source_run_id is None:
            record = record.model_copy(
                update={"proposal": record.proposal.model_copy(update={"source_run_id": self._spec.run_id})}
            )
        self.healing_records.append(record)
        if record.decision == HealingDecision.RECOVERED:
            event_type = "healing.accepted"
            payload: dict[str, Any] = {"attempt_id": record.attempt_id, "node_id": record.node_id}
        else:
            event_type = "healing.refused"
            payload = {
                "opportunity_id": record.opportunity_id,
                "reason": record.refusal_reason or record.error or "unknown",
            }
        await self._coordinator.recorder.record(
            workspace_id=self._spec.workspace_id,
            principal_id=self._spec.principal_id,
            run_id=self._spec.run_id,
            execution_id=self._spec.execution_id,
            event_type=event_type,
            actor=self._spec.actor,
            payload=payload,
        )

    async def evaluate_postcondition(self, node: ActionNode, name: str) -> bool | None:
        definition = self._spec.case.postcondition_defs.get(name)
        if definition is None:
            return None
        try:
            probe = await self._coordinator.read_port.probe(definition.condition, self._context_key)
        except Exception:
            self.storage_failures.append(f"postcondition:{name}")
            return None
        if probe.error_code is not None:
            return None
        return bool(probe.satisfied)

    async def _recover_evidence_targets(
        self,
        node: CheckpointNode,
        initial_facts: Any,
        observation: Observation,
    ) -> dict[str, TargetDescriptor]:
        healer = self._coordinator.active_healer
        if healer is None or self._spec.policy == "replay_strict":
            return {}
        pending = [
            assertion
            for assertion in node.assertions
            if assertion.target is not None
            and not _expects_absence(assertion)
            and initial_facts.count(assertion.target) != 1
        ]
        if not pending:
            return {}
        try:
            scene = await self._coordinator.scene_provider.scene(self._context_key)
        except Exception:
            self.storage_failures.append("healing_scene")
            return {}
        overrides: dict[str, TargetDescriptor] = {}
        for assertion in pending:
            target = assertion.target
            if target is None:
                continue
            decision = await healer.recover(
                target,
                scene,
                HealContext(
                    node_id=f"{node.id}:{assertion.id}",
                    actor=HealingActor.EVIDENCE,
                    scene_version=observation.version,
                ),
            )
            await self.record_healing(decision.record)
            if decision.recovered_target is not None:
                overrides[assertion.id] = decision.recovered_target
        return overrides

    async def dispatch_action(self, node: ActionNode, scene_version: int) -> ActionOutcomeView:
        payload: dict[str, Any] = {}
        if node.target is not None:
            payload["target"] = node.target.model_dump(mode="json")
        if node.value is not None:
            payload["value"] = node.value.model_dump(mode="json")
        if node.context is not None:
            if node.context.page:
                payload["page_key"] = node.context.page
            if node.context.frame:
                payload["frame_key"] = node.context.frame
        if node.operation.value == "navigate" and isinstance(payload.get("value"), dict):
            url = payload["value"].get("value")
            if isinstance(url, str) and url.startswith("/"):
                base = self._spec.target_base_url.rstrip("/") + "/"
                payload["value"] = {"kind": "literal", "value": urljoin(base, url.lstrip("/"))}
        request = CommandRequest(
            command_id=uuid4(),
            session_key=self._session_key,
            run_id=self._spec.run_id,
            attempt_id=self._spec.attempt_id,
            fence_epoch=self._spec.fence_epoch,
            control_revision=0,
            expected_observation_version=scene_version,
            operation=node.operation,
            payload=payload,
            side_effect=node.side_effect.value,
        )
        receipt = await self._coordinator.runtime.execute(request)
        if receipt.state == "unknown":
            self.unknown_commands.append(str(receipt.command_id))
        await self._coordinator.recorder.record(
            workspace_id=self._spec.workspace_id,
            principal_id=self._spec.principal_id,
            run_id=self._spec.run_id,
            execution_id=self._spec.execution_id,
            event_type="action.settled" if receipt.state == "settled" else f"action.{receipt.state}",
            actor=self._spec.actor,
            payload={"command_id": str(receipt.command_id), "outcome": receipt.outcome},
        )
        return ActionOutcomeView(
            command_id=receipt.command_id,
            state=receipt.state,
            outcome=receipt.outcome,
            evidence_refs=tuple(receipt.evidence),
            reason=receipt.reason,
        )

    async def evaluate_checkpoint(self, node: CheckpointNode) -> list[AssertionResult]:
        try:
            observation = await self._coordinator.read_port.observe(self._context_key, Modality.SEMANTIC)
            lane = self._coordinator.contexts.lane(self._context_key)
            await self._coordinator.runtime.journal.set_scene_version(
                self._session_key, scene_version=lane.observation_version
            )
        except Exception:
            self.storage_failures.append("observe")
            observation = Observation(
                observation_id=uuid4(),
                version=1,
                session_key=self._context_key,
                page_key="main",
                observed_at=datetime.now(UTC),
                mode=Modality.SEMANTIC,
                semantic_ref="unavailable://observe",
                size_bytes=0,
                redaction=RedactionStatus.FAILED,
            )
        evidence_map: dict[str, EvidenceStatus] = {}
        for assertion in node.assertions:
            try:
                ref = await self._coordinator.read_port.capture_safe_evidence(
                    self._context_key, f"checkpoint:{node.id}:{assertion.id}"
                )
                evidence_map[assertion.id] = EvidenceStatus.PRESENT if ref else EvidenceStatus.MISSING
            except Exception:
                evidence_map[assertion.id] = EvidenceStatus.MISSING
                self.storage_failures.append(assertion.id)
                await self._coordinator.recorder.record(
                    workspace_id=self._spec.workspace_id,
                    principal_id=self._spec.principal_id,
                    run_id=self._spec.run_id,
                    execution_id=self._spec.execution_id,
                    event_type="artifact.unavailable",
                    actor=self._spec.actor,
                    payload={"checkpoint_id": node.id, "assertion_id": assertion.id},
                )
        self.evidence_statuses.update(evidence_map)
        initial_facts = await capture_facts(
            self._coordinator.contexts,
            self._context_key,
            list(node.assertions),
            evidence_map,
            captures=self.captures,
            parameters=dict(self._spec.parameters),
            read_port=self._coordinator.read_port,
        )
        overrides = await self._recover_evidence_targets(node, initial_facts, observation)
        facts = await capture_facts(
            self._coordinator.contexts,
            self._context_key,
            list(node.assertions),
            evidence_map,
            overrides=overrides,
            captures=self.captures,
            parameters=dict(self._spec.parameters),
            read_port=self._coordinator.read_port,
        )
        request = CheckpointEvaluationRequest(
            run_id=self._spec.run_id,
            execution_id=self._spec.execution_id,
            step_id=node.id,
            checkpoint_id=node.id,
            assertions=list(node.assertions),
            observation=observation,
        )
        results = evaluate_checkpoint(request, facts)
        counts = {"passed": 0, "failed": 0, "errors": 0, "not_evaluated": 0}
        for result in results:
            if result.status == AssertionStatus.PASSED:
                counts["passed"] += 1
            elif result.status == AssertionStatus.FAILED:
                counts["failed"] += 1
            elif result.status == AssertionStatus.ERROR:
                counts["errors"] += 1
            else:
                counts["not_evaluated"] += 1
        await self._coordinator.recorder.record(
            workspace_id=self._spec.workspace_id,
            principal_id=self._spec.principal_id,
            run_id=self._spec.run_id,
            execution_id=self._spec.execution_id,
            event_type="checkpoint.evaluated",
            actor=self._spec.actor,
            payload={"checkpoint_id": node.id, **counts},
        )
        return results

    async def record_trace(self, label: str) -> str:
        try:
            return await self._coordinator.read_port.capture_safe_evidence(self._context_key, label)
        except Exception:
            self.storage_failures.append(label)
            return "unavailable"


class RunCoordinator:
    def __init__(
        self,
        *,
        runtime: SupervisorRuntime,
        contexts: ContextRegistry,
        read_port: PlaywrightReadPort,
        scene_provider: PlaywrightSceneProvider,
        fixtures: FixtureRegistry,
        recorder: Any,
        guard: TargetGuard | None = None,
        secret_namespace_hook: Callable[[str], None] | None = None,
        agent_models: AgentModels | None = None,
        taint: Any = None,
    ) -> None:
        self.runtime = runtime
        self.contexts = contexts
        self.read_port = read_port
        self.scene_provider = scene_provider
        self.fixtures = fixtures
        self.recorder = recorder
        self.guard = guard or TargetGuard()
        self._secret_namespace_hook = secret_namespace_hook
        self._active_spec: ExecutionSpec | None = None
        self.agent_models = agent_models or AgentModels()
        self.taint = taint
        self.active_healer: Healer | None = None

    async def apply_control(self, control_id: UUID) -> dict[str, Any]:
        result = await self.runtime.apply_control(control_id)
        if self._active_spec is not None:
            await self.recorder.record(
                workspace_id=self._active_spec.workspace_id,
                principal_id=self._active_spec.principal_id,
                run_id=self._active_spec.run_id,
                event_type="control.effective",
                actor=self._active_spec.actor,
                payload={"control_id": str(control_id)},
            )
        return result

    async def execute(self, spec: ExecutionSpec) -> ExecutionOutcome:
        self._active_spec = spec
        agent_policy = spec.policy in AGENT_POLICIES
        if agent_policy:
            try:
                validate_mode_policy_modality(
                    RunMode.AGENT,
                    PolicyKind(spec.policy),
                    Modality(spec.observation_mode),
                )
            except (AgentQAValidationError, ValueError):
                return self._terminal(
                    spec,
                    ExecutionStatus.ERROR,
                    "inconclusive",
                    None,
                    ["policy_config_invalid"],
                    {"supported": False},
                    [],
                    CompletionOutcome(False, False),
                    [],
                    [],
                )
        if self._secret_namespace_hook is not None:
            self._secret_namespace_hook(spec.namespace)
        session_key = f"exec-{spec.execution_id}"
        context_key = str(spec.run_id)
        await self.recorder.record(
            workspace_id=spec.workspace_id,
            principal_id=spec.principal_id,
            run_id=spec.run_id,
            execution_id=spec.execution_id,
            event_type="run.state_changed",
            actor=spec.actor,
            payload={"status": "running", "execution_id": str(spec.execution_id)},
        )
        try:
            case = resolve_parameters(spec.case, spec.parameters)
        except MissingParameterError as exc:
            return self._terminal(
                spec,
                ExecutionStatus.ERROR,
                None,
                None,
                ["input_invalid"],
                {"supported": False},
                [],
                CompletionOutcome(False, False),
                [],
                [str(exc)],
            )
        capability = validate_case(case)
        if not capability.supported:
            completion = CompletionOutcome(
                complete=False,
                proof_valid=False,
                reasons=("capability_unavailable",),
            )
            return self._terminal(
                spec,
                ExecutionStatus.ERROR,
                "inconclusive",
                None,
                ["capability_unavailable", *capability.reasons],
                capability.as_dict(),
                [],
                completion,
                [],
                [],
            )
        fixture_receipt = self.fixtures.prepare(spec.fixture_ref, spec.namespace)
        if not fixture_receipt.ok:
            completion = CompletionOutcome(complete=False, proof_valid=False, reasons=("fixture_failed",))
            return self._terminal(
                spec,
                ExecutionStatus.ERROR,
                "inconclusive",
                None,
                ["fixture_failed"],
                capability.as_dict(),
                [],
                completion,
                [],
                [],
            )
        await self.runtime.open_session(
            run_id=spec.run_id,
            attempt_id=spec.attempt_id,
            session_key=session_key,
            fence_epoch=spec.fence_epoch,
        )
        await self.contexts.open(context_key)
        hooks = _CoordinatorHooks(self, spec, session_key, context_key)
        self.active_healer = self._build_healer(spec)
        if agent_policy:
            bundle = await run_agent_bundle(
                self,
                spec,
                hooks,
                case=case,
                composition=self.agent_models,
                taint=self.taint,
            )
        else:
            runner = ReplayRunner(case, hooks=hooks, guard=self.guard, healer=self.active_healer, actor=spec.actor)
            replay = await runner.run()
            bundle = bundle_from_replay(replay)
        self.active_healer = None
        if bundle.aborted_reason is not None:
            await self.recorder.record(
                workspace_id=spec.workspace_id,
                principal_id=spec.principal_id,
                run_id=spec.run_id,
                execution_id=spec.execution_id,
                event_type="execution.aborted",
                actor=spec.actor,
                payload={
                    "reason": bundle.aborted_reason,
                    "degraded": bundle.degraded,
                    "policy_versions": list(bundle.policy_versions),
                },
            )
        plan = CompletionPlan.from_case(case)
        proof = ExecutionProof(
            visited_nodes=frozenset(bundle.visited_nodes),
            branch_decisions=dict(bundle.branch_decisions),
            checkpoint_receipts=frozenset(bundle.checkpoint_receipts),
        )
        completion = evaluate_completion(plan, proof)
        applicable = {}
        for assertion in plan.required_assertions:
            state, _reason = assertion_applicability(plan, proof, assertion)
            applicable[assertion] = bool(state)
        status = _execution_status(bundle.aborted_reason)
        healing_records = list(hooks.healing_records) or list(bundle.healing_records)
        healed = any(record.decision == HealingDecision.RECOVERED for record in healing_records)
        healing_guards_ok = self._healing_guards_ok(healing_records)
        attempt = AttemptEvidence(
            attempt_no=spec.fence_epoch,
            execution_status=status,
            results=tuple(bundle.assertion_results),
            completion=completion,
            applicable=applicable,
            recovered=healed,
            revision_ready=not spec.provisional,
        )
        run_result = reduce_verdict(spec.run_id, [attempt], required_assertions=plan.required_assertions)
        evidence_ok = not any(
            result.evidence_status != EvidenceStatus.PRESENT
            for result in bundle.assertion_results
            if result.status == AssertionStatus.ERROR
        )
        gate = evaluate_gate(
            spec.gate_profile if spec.gate_profile in ("strict", "allow_healing") else "strict",
            run_result.verdict,
            GateContext(
                completed=completion.complete,
                revision_ready=not spec.provisional,
                evidence_ok=evidence_ok,
                healed=healed,
                healing_guards_ok=healing_guards_ok,
                degraded=bundle.degraded,
                provisional=spec.provisional,
            ),
        )
        outcome_probe: dict[str, Any] | None = None
        try:
            outcome_probe = self.fixtures.probe(spec.fixture_ref, spec.namespace)
        except Exception:
            outcome_probe = None
        await self.recorder.record(
            workspace_id=spec.workspace_id,
            principal_id=spec.principal_id,
            run_id=spec.run_id,
            execution_id=spec.execution_id,
            event_type="fixture.probed",
            actor=spec.actor,
            payload={"probe": outcome_probe or {}},
        )
        cleanup_failed = False
        try:
            cleanup = self.fixtures.cleanup(spec.fixture_ref, spec.namespace)
            cleanup_failed = not cleanup.ok
        except Exception:
            cleanup_failed = True
        with contextlib.suppress(Exception):
            await self.contexts.close(context_key)
        with contextlib.suppress(Exception):
            await self.runtime.close_session(
                session_key,
                reason="unknown_outcome" if hooks.unknown_commands else "completed",
                quarantine=bool(hooks.unknown_commands),
            )
        outcome = ExecutionOutcome(
            execution_id=spec.execution_id,
            status=run_result.status.value,
            verdict=run_result.verdict.value if run_result.verdict else None,
            gate=gate.result.value,
            gate_reasons=list(gate.reasons),
            reasons=list(run_result.reasons)
            + (["cleanup_failed"] if cleanup_failed else [])
            + (["provisional"] if spec.provisional else [])
            + (["healed"] if healed else []),
            capability=capability.as_dict(),
            steps=[
                {
                    "node_id": step.node_id,
                    "kind": step.kind,
                    "status": step.status,
                    "detail": step.detail,
                }
                for step in bundle.steps
            ],
            assertion_results=list(bundle.assertion_results),
            completion=completion,
            trace_refs=list(bundle.trace_refs),
            unknown_commands=list(hooks.unknown_commands),
            cleanup_failed=cleanup_failed,
            outcome_probe=outcome_probe,
            degraded=bundle.degraded,
            policy_versions=list(bundle.policy_versions),
            healing_records=healing_records,
        )
        return outcome

    def _build_healer(self, spec: ExecutionSpec) -> Healer | None:
        if spec.policy != "replay_healing" or spec.healing_profile is None:
            return None
        return build_healer(spec.healing_profile, decision=self.agent_models.decision)

    @staticmethod
    def _healing_guards_ok(records: list[HealingRecord]) -> bool:
        recovered = [record for record in records if record.decision == HealingDecision.RECOVERED]
        if not recovered:
            return False
        for record in recovered:
            if not record.guard_checks:
                return False
            if record.postconditions_ok is False:
                return False
            if record.actor == HealingActor.ACTION and record.dispatch_outcome != "succeeded":
                return False
        return True

    def _terminal(
        self,
        spec: ExecutionSpec,
        status: ExecutionStatus,
        verdict: str | None,
        gate: str | None,
        reasons: list[str],
        capability: dict[str, Any],
        steps: list[dict[str, Any]],
        completion: CompletionOutcome,
        assertion_results: list[AssertionResult],
        trace_refs: list[str],
    ) -> ExecutionOutcome:
        return ExecutionOutcome(
            execution_id=spec.execution_id,
            status=status.value,
            verdict=verdict,
            gate=gate,
            gate_reasons=[],
            reasons=reasons,
            capability=capability,
            steps=steps,
            assertion_results=assertion_results,
            completion=completion,
            trace_refs=trace_refs,
            unknown_commands=[],
        )


class MissingParameterError(ValueError):
    pass


def outcome_to_dict(outcome: ExecutionOutcome) -> dict[str, Any]:
    return {
        "execution_id": str(outcome.execution_id),
        "status": outcome.status,
        "verdict": outcome.verdict,
        "gate": outcome.gate,
        "gate_reasons": list(outcome.gate_reasons),
        "reasons": list(outcome.reasons),
        "capability": outcome.capability,
        "steps": outcome.steps,
        "assertion_results": [result.model_dump(mode="json") for result in outcome.assertion_results],
        "completion": {
            "complete": outcome.completion.complete,
            "proof_valid": outcome.completion.proof_valid,
            "missing_nodes": list(outcome.completion.missing_nodes),
            "missing_receipts": list(outcome.completion.missing_receipts),
            "reasons": list(outcome.completion.reasons),
        },
        "trace_refs": list(outcome.trace_refs),
        "unknown_commands": list(outcome.unknown_commands),
        "cleanup_failed": outcome.cleanup_failed,
        "outcome_probe": outcome.outcome_probe,
        "degraded": outcome.degraded,
        "policy_versions": list(outcome.policy_versions),
        "healing_records": [record.model_dump(mode="json") for record in outcome.healing_records],
    }


def outcome_from_dict(data: dict[str, Any]) -> ExecutionOutcome:
    completion = data.get("completion", {})
    return ExecutionOutcome(
        execution_id=UUID(str(data["execution_id"])),
        status=str(data["status"]),
        verdict=data.get("verdict"),
        gate=data.get("gate"),
        gate_reasons=list(data.get("gate_reasons", [])),
        reasons=list(data.get("reasons", [])),
        capability=dict(data.get("capability", {})),
        steps=list(data.get("steps", [])),
        assertion_results=[AssertionResult.model_validate(item) for item in data.get("assertion_results", [])],
        completion=CompletionOutcome(
            complete=bool(completion.get("complete", False)),
            proof_valid=bool(completion.get("proof_valid", False)),
            missing_nodes=tuple(completion.get("missing_nodes", [])),
            missing_receipts=tuple(completion.get("missing_receipts", [])),
            reasons=tuple(completion.get("reasons", [])),
        ),
        trace_refs=list(data.get("trace_refs", [])),
        unknown_commands=list(data.get("unknown_commands", [])),
        cleanup_failed=bool(data.get("cleanup_failed", False)),
        outcome_probe=data.get("outcome_probe"),
        degraded=bool(data.get("degraded", False)),
        policy_versions=list(data.get("policy_versions", [])),
        healing_records=[HealingRecord.model_validate(item) for item in data.get("healing_records", [])],
    )


def resolve_parameters(case: CaseContent, parameters: dict[str, str]) -> CaseContent:
    document = case.model_dump(mode="json")
    for name, definition in case.parameter_defs.items():
        if definition.required and name not in parameters:
            raise MissingParameterError(name)
    _substitute(document.get("nodes", []), parameters)
    for postcondition in document.get("postcondition_defs", {}).values():
        _substitute_condition(postcondition.get("condition", {}), parameters)
    return CaseContent.model_validate(document)


def _substitute(nodes: list[dict[str, Any]], parameters: dict[str, str]) -> None:
    for node in nodes:
        value = node.get("value")
        if isinstance(value, dict):
            node["value"] = _substitute_expr(value, parameters)
        target = node.get("target")
        if isinstance(target, dict):
            _substitute_target(target, parameters)
        probe = node.get("probe")
        if isinstance(probe, dict):
            _substitute_condition(probe, parameters)
        condition = node.get("condition")
        if isinstance(condition, dict):
            _substitute_condition(condition, parameters)
        for assertion in node.get("assertions", []):
            _substitute_assertion(assertion, parameters)
        _substitute(node.get("then_nodes", []), parameters)
        _substitute(node.get("else_nodes", []), parameters)
        _substitute(node.get("body", []), parameters)


def _substitute_assertion(assertion: dict[str, Any], parameters: dict[str, str]) -> None:
    if isinstance(assertion.get("expected"), dict):
        assertion["expected"] = _substitute_expr(assertion["expected"], parameters)
    if isinstance(assertion.get("target"), dict):
        _substitute_target(assertion["target"], parameters)


def _substitute_target(target: dict[str, Any], parameters: dict[str, str]) -> None:
    scope = target.get("entity_scope")
    if isinstance(scope, dict) and isinstance(scope.get("value"), dict):
        scope["value"] = _substitute_expr(scope["value"], parameters)


def _substitute_condition(condition: dict[str, Any], parameters: dict[str, str]) -> None:
    if isinstance(condition.get("expected"), dict):
        condition["expected"] = _substitute_expr(condition["expected"], parameters)
    if isinstance(condition.get("target"), dict):
        _substitute_target(condition["target"], parameters)
    for child in condition.get("conditions", []):
        _substitute_condition(child, parameters)
    if isinstance(condition.get("condition"), dict):
        _substitute_condition(condition["condition"], parameters)


def _substitute_expr(expr: dict[str, Any], parameters: dict[str, str]) -> dict[str, Any]:
    if expr.get("kind") == "parameter":
        name = expr.get("name", "")
        if name not in parameters:
            raise MissingParameterError(name)
        return {"kind": "literal", "value": parameters[name]}
    return expr


def _execution_status(aborted_reason: str | None) -> ExecutionStatus:
    if aborted_reason is None or aborted_reason.startswith("policy_stop"):
        return ExecutionStatus.SUCCEEDED
    if "control_cancelled" in aborted_reason:
        return ExecutionStatus.CANCELLED
    return ExecutionStatus.ERROR


def _expects_absence(assertion: Any) -> bool:
    from agentqa.contracts.verification import Comparator

    expected = assertion.expected
    value = expected.value if isinstance(expected, LiteralValue) else None
    if assertion.comparator in (Comparator.COUNT_EQUALS, Comparator.COUNT_GREATER_OR_EQUAL) and value == 0:
        return True
    return assertion.comparator in (Comparator.VISIBLE, Comparator.EXISTS) and value is False
