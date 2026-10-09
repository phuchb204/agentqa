from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from agentqa.agent.planning.observation import AgentObservation
from agentqa.agent.replay.runner import ActionOutcomeView
from agentqa.contracts.actions import Operation, SideEffectClass
from agentqa.contracts.case import ActionNode, CaseContent, CheckpointNode, Completion
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.observation import Actionability, Modality, SemanticCandidate
from agentqa.contracts.policies import PolicyOutcome
from agentqa.contracts.verification import AssertionResult, AssertionStatus, Comparator, EvidenceStatus


def make_candidate(
    candidate_id: str,
    role: str = "button",
    name: str = "Đăng nhập",
    *,
    visible: bool = True,
    enabled: bool = True,
    actionability: Actionability = Actionability.ACTIONABLE,
    provenance: str = "dom",
) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=candidate_id,
        role=role,
        name=name,
        visible=visible,
        actionability=actionability,
        provenance=provenance,
    )


def make_observation(
    candidates: list[SemanticCandidate],
    *,
    scene_version: int = 1,
    truncated: bool = False,
    none_context_sentinel: bool = False,
) -> AgentObservation:
    return AgentObservation(
        observation_id=uuid4(),
        scene_version=scene_version,
        modality=Modality.SEMANTIC,
        candidates=candidates,
        payload={
            "observation_id": str(uuid4()),
            "version": 1,
            "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        },
        truncated=truncated,
        none_context_sentinel=none_context_sentinel,
    )


def action_node(
    node_id: str = "login_submit",
    *,
    operation: Operation = Operation.CLICK,
    intent: str = "login_submit",
    role: str = "button",
    name: str = "Đăng nhập",
    side_effect: SideEffectClass = SideEffectClass.REVERSIBLE,
    value=None,
) -> ActionNode:
    return ActionNode(
        kind="action",
        id=node_id,
        operation=operation,
        target=TargetDescriptor(intent=intent, role=role, name=name),
        value=value,
        side_effect=side_effect,
    )


def make_case(
    *,
    nodes: list,
    required_nodes: list[str] | None = None,
    required_assertions: list[str] | None = None,
    logical_key: str = "agent_case",
) -> CaseContent:
    return CaseContent(
        schema_version="case/1",
        logical_key=logical_key,
        title="Ca agent",
        goal="Hoàn thành mục tiêu ca",
        requirements=["req-1"],
        nodes=nodes,
        completion=Completion(
            required_nodes=required_nodes if required_nodes is not None else [node.id for node in nodes],
            required_assertions=required_assertions or [],
        ),
    )


def checkpoint_node(node_id: str = "result", assertion_id: str = "item_exists_once") -> CheckpointNode:
    return CheckpointNode(
        kind="checkpoint",
        id=node_id,
        assertions=[
            {
                "id": assertion_id,
                "comparator": Comparator.COUNT_EQUALS,
                "target": TargetDescriptor(intent="created_item_row", role="listitem"),
                "required": True,
            }
        ],
    )


def assertion_result(
    assertion_id: str,
    status: AssertionStatus = AssertionStatus.PASSED,
    *,
    evidence: EvidenceStatus = EvidenceStatus.PRESENT,
) -> AssertionResult:
    return AssertionResult(
        run_id=uuid4(),
        execution_id=uuid4(),
        step_id="result",
        assertion_id=assertion_id,
        status=status,
        evidence_status=evidence,
    )


def action_view(
    *,
    succeeded: bool = True,
    outcome: str | None = None,
    reason: str | None = None,
    state: str | None = None,
) -> ActionOutcomeView:
    resolved_outcome = outcome or ("succeeded" if succeeded else "failed")
    resolved_state = state or ("settled" if succeeded else "rejected")
    return ActionOutcomeView(
        command_id=uuid4(),
        state=resolved_state,
        outcome=resolved_outcome,
        evidence_refs=("evidence://1",) if succeeded else (),
        reason=reason,
    )


class FakeHooks:
    def __init__(
        self,
        observations: list[AgentObservation],
        *,
        dispatch_results: list[ActionOutcomeView] | None = None,
        checkpoint_results: list[list[tuple[str, list[AssertionResult]]]] | None = None,
    ) -> None:
        self._observations = list(observations)
        self._dispatch_results = list(dispatch_results or [])
        self._checkpoint_results = list(checkpoint_results or [])
        self.dispatched: list[ActionNode] = []
        self.checkpoint_calls = 0
        self.traces: list[str] = []

    async def observe(self) -> AgentObservation:
        if len(self._observations) > 1:
            return self._observations.pop(0)
        return self._observations[0]

    async def dispatch(self, action: ActionNode, scene_version: int) -> ActionOutcomeView:
        self.dispatched.append(action)
        if self._dispatch_results:
            return self._dispatch_results.pop(0)
        return action_view(succeeded=True)

    async def evaluate_checkpoints(self) -> list[tuple[str, list[AssertionResult]]]:
        self.checkpoint_calls += 1
        if self._checkpoint_results:
            return self._checkpoint_results.pop(0)
        return []

    async def record_trace(self, label: str) -> str:
        self.traces.append(label)
        return f"trace://{label}"


class ScriptedPolicy:
    def __init__(self, outcomes: list[PolicyOutcome]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    async def propose(self, *, observation, plan, history) -> PolicyOutcome:
        self.calls += 1
        if len(self._outcomes) > 1:
            return self._outcomes.pop(0)
        return self._outcomes[0]


@dataclass
class RecordedCall:
    purpose: str
    model: str


@dataclass
class FakeComposition:
    generative: object | None = None
    decision: object | None = None
    value_generator: object | None = None
    calls: list[RecordedCall] = field(default_factory=list)


def utc_now():
    return datetime.now(UTC)


__all__ = [
    "FakeComposition",
    "FakeHooks",
    "RecordedCall",
    "ScriptedPolicy",
    "action_node",
    "action_view",
    "assertion_result",
    "checkpoint_node",
    "make_candidate",
    "make_case",
    "make_observation",
    "utc_now",
]
