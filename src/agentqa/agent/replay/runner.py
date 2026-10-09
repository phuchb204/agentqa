from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from agentqa.agent.identity.guard import GuardContext, TargetGuard
from agentqa.agent.identity.resolver import SceneCandidate
from agentqa.agent.replay.capabilities import CapabilityReport, validate_case
from agentqa.contracts.case import ActionNode, CaseContent, CaseNode, CheckpointNode
from agentqa.contracts.verification import AssertionResult


@dataclass(frozen=True)
class ActionOutcomeView:
    command_id: UUID
    state: str
    outcome: str
    evidence_refs: tuple[str, ...] = ()
    reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.state == "settled" and self.outcome == "succeeded"


@dataclass(frozen=True)
class StepRecord:
    node_id: str
    kind: str
    status: str
    detail: dict[str, object] = field(default_factory=dict)


@dataclass
class ReplayOutcome:
    capability: CapabilityReport
    steps: list[StepRecord] = field(default_factory=list)
    visited_nodes: list[str] = field(default_factory=list)
    branch_decisions: dict[str, str] = field(default_factory=dict)
    checkpoint_receipts: set[str] = field(default_factory=set)
    assertion_results: list[AssertionResult] = field(default_factory=list)
    guard_proofs: list[dict[str, object]] = field(default_factory=list)
    trace_refs: list[str] = field(default_factory=list)
    aborted_reason: str | None = None
    aborted_node: str | None = None


class ReplayHooks(Protocol):
    async def current_scene_version(self) -> int: ...

    async def scene(self) -> list[SceneCandidate]: ...

    async def dispatch_action(self, node: ActionNode, scene_version: int) -> ActionOutcomeView: ...

    async def evaluate_checkpoint(self, node: CheckpointNode) -> list[AssertionResult]: ...

    async def record_trace(self, label: str) -> str: ...


class ReplayRunner:
    def __init__(
        self,
        case: CaseContent,
        *,
        hooks: ReplayHooks,
        guard: TargetGuard | None = None,
        actor: str = "replay",
    ) -> None:
        self._case = case
        self._hooks = hooks
        self._guard = guard or TargetGuard()
        self._actor = actor

    async def run(self) -> ReplayOutcome:
        capability = validate_case(self._case)
        outcome = ReplayOutcome(capability=capability)
        if not capability.supported:
            outcome.aborted_reason = "capability_unavailable"
            return outcome
        for node in self._case.nodes:
            if not await self._run_node(node, outcome):
                break
        return outcome

    async def _run_node(self, node: CaseNode, outcome: ReplayOutcome) -> bool:
        if isinstance(node, ActionNode):
            return await self._run_action(node, outcome)
        if isinstance(node, CheckpointNode):
            return await self._run_checkpoint(node, outcome)
        outcome.aborted_reason = f"node_kind_not_supported:{node.kind}"
        outcome.aborted_node = node.id
        return False

    async def _run_action(self, node: ActionNode, outcome: ReplayOutcome) -> bool:
        scene_version = await self._hooks.current_scene_version()
        if node.target is not None:
            scene = await self._hooks.scene()
            decision = self._guard.check(
                node.target,
                scene,
                GuardContext(
                    operation=node.operation,
                    expected_scene_version=scene_version,
                    current_scene_version=scene_version,
                ),
            )
            outcome.guard_proofs.append({"node_id": node.id, **decision.as_dict()})
            if not decision.allowed:
                outcome.steps.append(
                    StepRecord(
                        node_id=node.id,
                        kind="action",
                        status="guard_rejected",
                        detail={
                            "code": decision.code.value if decision.code else None,
                            "reason": decision.reason,
                        },
                    )
                )
                outcome.aborted_reason = f"guard_rejected:{decision.reason or 'unknown'}"
                outcome.aborted_node = node.id
                return False
        result = await self._hooks.dispatch_action(node, scene_version)
        step_status = "settled" if result.succeeded else result.state
        outcome.steps.append(
            StepRecord(
                node_id=node.id,
                kind="action",
                status=step_status,
                detail={
                    "command_id": str(result.command_id),
                    "outcome": result.outcome,
                    "evidence_refs": list(result.evidence_refs),
                    "reason": result.reason,
                },
            )
        )
        outcome.visited_nodes.append(node.id)
        if not result.succeeded:
            outcome.aborted_reason = f"action_not_settled:{result.reason or result.outcome}"
            outcome.aborted_node = node.id
            return False
        return True

    async def _run_checkpoint(self, node: CheckpointNode, outcome: ReplayOutcome) -> bool:
        results = await self._hooks.evaluate_checkpoint(node)
        outcome.assertion_results.extend(results)
        proof_ref = await self._hooks.record_trace(f"checkpoint:{node.id}")
        outcome.trace_refs.append(proof_ref)
        outcome.checkpoint_receipts.add(node.id)
        outcome.visited_nodes.append(node.id)
        outcome.steps.append(
            StepRecord(
                node_id=node.id,
                kind="checkpoint",
                status="evaluated",
                detail={
                    "assertions": {result.assertion_id: result.status.value for result in results},
                    "proof_ref": proof_ref,
                },
            )
        )
        return True
