from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from agentqa.agent.history import ActionHistory
from agentqa.agent.observation.semantic import RawCandidate, RawScene, SemanticObservationBuilder, semantic_payload
from agentqa.agent.planning.observation import AgentObservation
from agentqa.agent.planning.runner import AgentRunner, AgentRunOutcome
from agentqa.agent.policies.cascade import JevCascadePolicy
from agentqa.agent.policies.llm import LLMPolicy
from agentqa.agent.policies.profiles import CASCADE_PROFILE, LLM_PROFILE, profile_for
from agentqa.agent.policies.values import ValueGenerator, ValueResolver
from agentqa.agent.replay.runner import ActionOutcomeView, StepRecord
from agentqa.contracts.canonical import digest_content
from agentqa.contracts.case import ActionNode, CaseContent, CheckpointNode
from agentqa.contracts.healing import HealingRecord
from agentqa.contracts.observation import Actionability, Modality
from agentqa.contracts.policies import PolicyKind, RunMode, validate_mode_policy_modality
from agentqa.contracts.ports import DecisionModelPort, GenerativeModelPort
from agentqa.contracts.verification import AssertionResult
from agentqa.platform.security.taint import TaintRegistry


@dataclass
class AgentModels:
    generative: GenerativeModelPort | None = None
    decision: DecisionModelPort | None = None
    value_generator: ValueGenerator | None = None


@dataclass
class RunBundle:
    steps: list[StepRecord] = field(default_factory=list)
    visited_nodes: list[str] = field(default_factory=list)
    branch_decisions: dict[str, str] = field(default_factory=dict)
    checkpoint_receipts: set[str] = field(default_factory=set)
    assertion_results: list[AssertionResult] = field(default_factory=list)
    trace_refs: list[str] = field(default_factory=list)
    aborted_reason: str | None = None
    degraded: bool = False
    policy_versions: list[str] = field(default_factory=list)
    healing_records: list[HealingRecord] = field(default_factory=list)
    captures: dict[str, object] = field(default_factory=dict)
    visited_instances: list[str] = field(default_factory=list)


class CoordinatorHooksPort(Protocol):
    async def current_scene_version(self) -> int: ...

    async def scene(self) -> list[Any]: ...

    async def dispatch_action(self, node: ActionNode, scene_version: int) -> ActionOutcomeView: ...

    async def evaluate_checkpoint(self, node: CheckpointNode) -> list[AssertionResult]: ...

    async def record_trace(self, label: str) -> str: ...


class _AgentHooks:
    def __init__(
        self,
        coordinator: Any,
        spec: Any,
        hooks: CoordinatorHooksPort,
        *,
        modality: Modality,
        case: CaseContent,
        taint: TaintRegistry | None,
    ) -> None:
        self._coordinator = coordinator
        self._spec = spec
        self._hooks = hooks
        self._modality = modality
        self._case = case
        self._builder = SemanticObservationBuilder(taint=taint)

    async def observe(self) -> AgentObservation:
        scene_version = await self._hooks.current_scene_version()
        scene = await self._hooks.scene()
        raw = RawScene(
            url="",
            title=None,
            scene_version=scene_version,
            candidates=[
                RawCandidate(
                    source_id=candidate.candidate_id,
                    role=candidate.role or "unknown",
                    name=candidate.name or "",
                    text=candidate.text or "",
                    visible=bool(candidate.visible),
                    enabled=bool(candidate.enabled),
                    actionability=_actionability(candidate),
                    entity_key=candidate.entity_text,
                    attributes=dict(candidate.attributes),
                )
                for candidate in scene
            ],
        )
        snapshot, audit = self._builder.build(
            raw,
            observation_id=uuid4(),
            version=max(scene_version, 1),
            session_key=f"exec-{self._spec.execution_id}",
            page_key="main",
        )
        return AgentObservation(
            observation_id=snapshot.observation_id,
            scene_version=scene_version,
            modality=self._modality,
            candidates=list(snapshot.candidates),
            payload=semantic_payload(snapshot),
            truncated=snapshot.budget.truncated,
            none_context_sentinel=snapshot.budget.none_context_sentinel,
            audit=audit,
        )

    async def dispatch(self, action: ActionNode, scene_version: int) -> ActionOutcomeView:
        return await self._hooks.dispatch_action(action, scene_version)

    async def evaluate_checkpoints(self) -> list[tuple[str, list[AssertionResult]]]:
        evaluations: list[tuple[str, list[AssertionResult]]] = []
        for node in self._case.nodes:
            if isinstance(node, CheckpointNode):
                results = await self._hooks.evaluate_checkpoint(node)
                evaluations.append((node.id, results))
        return evaluations

    async def record_trace(self, label: str) -> str:
        return await self._hooks.record_trace(label)


def build_policy(composition: AgentModels, policy_kind: PolicyKind, *, profile=None):
    if policy_kind is PolicyKind.JEV_CASCADE:
        if composition.decision is None:
            return None
        fallback = LLMPolicy(composition.generative, profile=LLM_PROFILE) if composition.generative else None
        return JevCascadePolicy(composition.decision, profile=profile or CASCADE_PROFILE, fallback=fallback)
    if composition.generative is None:
        return None
    return LLMPolicy(composition.generative, profile=profile or LLM_PROFILE)


async def run_agent_bundle(
    coordinator: Any,
    spec: Any,
    hooks: CoordinatorHooksPort,
    *,
    case: CaseContent,
    composition: AgentModels,
    taint: TaintRegistry | None = None,
) -> RunBundle:
    policy_kind = PolicyKind(spec.policy)
    modality = Modality(spec.observation_mode)
    validate_mode_policy_modality(RunMode.AGENT, policy_kind, modality)
    profile = profile_for(policy_kind)
    policy = build_policy(composition, policy_kind, profile=profile)
    if policy is None:
        return RunBundle(aborted_reason="agent_models_unavailable")
    history = ActionHistory(run_snapshot_digest=spec.snapshot_digest or digest_content(case))
    resolver = ValueResolver(
        generator=composition.value_generator,
        generator_allowed=composition.value_generator is not None,
    )
    runner = AgentRunner(
        case,
        hooks=_AgentHooks(coordinator, spec, hooks, modality=modality, case=case, taint=taint),
        policy=policy,
        profile=profile,
        value_resolver=resolver,
        history=history,
        parameters=dict(spec.parameters),
    )
    outcome = await runner.run()
    return bundle_from_agent(outcome)


def bundle_from_agent(outcome: AgentRunOutcome) -> RunBundle:
    return RunBundle(
        steps=list(outcome.steps),
        visited_nodes=list(dict.fromkeys(outcome.visited_nodes)),
        checkpoint_receipts=set(outcome.checkpoint_receipts),
        assertion_results=list(outcome.assertion_results),
        trace_refs=list(outcome.trace_refs),
        aborted_reason=outcome.aborted_reason,
        degraded=outcome.degraded,
        policy_versions=list(outcome.policy_versions),
    )


def bundle_from_replay(replay: Any) -> RunBundle:
    return RunBundle(
        steps=list(replay.steps),
        visited_nodes=list(replay.visited_nodes),
        branch_decisions=dict(replay.branch_decisions),
        checkpoint_receipts=set(replay.checkpoint_receipts),
        assertion_results=list(replay.assertion_results),
        trace_refs=list(replay.trace_refs),
        aborted_reason=replay.aborted_reason,
        degraded=False,
        policy_versions=[],
        healing_records=list(getattr(replay, "healing_records", [])),
        captures=dict(getattr(replay, "captures", {})),
        visited_instances=list(getattr(replay, "visited_instances", [])),
    )


def _actionability(candidate) -> Actionability:
    if not candidate.enabled:
        return Actionability.DISABLED
    if not candidate.visible:
        return Actionability.OFFSCREEN
    return Actionability.ACTIONABLE
