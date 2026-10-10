from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from agentqa.agent.healing import HealContext, HealDecision, Healer
from agentqa.agent.identity.guard import GuardContext, TargetGuard
from agentqa.agent.identity.resolver import SceneCandidate
from agentqa.agent.replay.branches import evaluate_condition
from agentqa.agent.replay.capabilities import CapabilityReport, validate_case
from agentqa.agent.replay.captures import run_capture
from agentqa.agent.replay.contexts import RuntimeContext
from agentqa.agent.replay.loops import run_loop
from agentqa.contracts.case import (
    ActionNode,
    BranchNode,
    CaptureNode,
    CaseContent,
    CaseNode,
    CheckpointNode,
    ComparisonCondition,
    LoopNode,
)
from agentqa.contracts.healing import HealingActor, HealingRecord
from agentqa.contracts.identity import TargetDescriptor
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
    healing_records: list[HealingRecord] = field(default_factory=list)
    trace_refs: list[str] = field(default_factory=list)
    captures: dict[str, object] = field(default_factory=dict)
    visited_instances: list[str] = field(default_factory=list)
    aborted_reason: str | None = None
    aborted_node: str | None = None


class ReplayHooks(Protocol):
    async def current_scene_version(self) -> int: ...

    async def scene(self) -> list[SceneCandidate]: ...

    async def dispatch_action(self, node: ActionNode, scene_version: int) -> ActionOutcomeView: ...

    async def evaluate_checkpoint(self, node: CheckpointNode) -> list[AssertionResult]: ...

    async def evaluate_postcondition(self, node: ActionNode, name: str) -> bool | None: ...

    async def probe_condition(self, condition: ComparisonCondition) -> bool | None: ...

    async def capture_probe(self, probe: ComparisonCondition) -> tuple[bool, str | None]: ...

    async def sync_captures(self, captures: dict[str, object]) -> None: ...

    async def record_healing(self, record: HealingRecord) -> None: ...

    async def record_trace(self, label: str) -> str: ...


class ReplayRunner:
    def __init__(
        self,
        case: CaseContent,
        *,
        hooks: ReplayHooks,
        guard: TargetGuard | None = None,
        healer: Healer | None = None,
        actor: str = "replay",
    ) -> None:
        self._case = case
        self._hooks = hooks
        self._guard = guard or TargetGuard()
        self._healer = healer
        self._actor = actor

    async def run(self) -> ReplayOutcome:
        capability = validate_case(self._case)
        outcome = ReplayOutcome(capability=capability)
        if not capability.supported:
            outcome.aborted_reason = "capability_unavailable"
            return outcome
        ctx = RuntimeContext()
        for node in self._case.nodes:
            if not await self._run_node(node, outcome, ctx):
                break
        outcome.branch_decisions = dict(ctx.branch_decisions)
        outcome.captures = dict(ctx.captures)
        outcome.visited_instances = list(ctx.visited_instances)
        return outcome

    async def _run_node(self, node: CaseNode, outcome: ReplayOutcome, ctx: RuntimeContext) -> bool:
        if isinstance(node, ActionNode):
            return await self._run_action(node, outcome, ctx)
        if isinstance(node, CheckpointNode):
            return await self._run_checkpoint(node, outcome)
        if isinstance(node, CaptureNode):
            return await self._run_capture_node(node, outcome, ctx)
        if isinstance(node, BranchNode):
            return await self._run_branch(node, outcome, ctx)
        if isinstance(node, LoopNode):
            return await self._run_loop_node(node, outcome, ctx)
        outcome.aborted_reason = f"node_kind_not_supported:{node.kind}"
        outcome.aborted_node = node.id
        return False

    async def _run_capture_node(self, node: CaptureNode, outcome: ReplayOutcome, ctx: RuntimeContext) -> bool:
        satisfied, observed = await run_capture(node, ctx, self._hooks)
        await self._hooks.sync_captures(ctx.captures)
        outcome.visited_nodes.append(node.id)
        outcome.steps.append(
            StepRecord(
                node_id=node.id,
                kind="capture",
                status="captured",
                detail={
                    "output": node.output.name,
                    "type": node.output.type.value,
                    "taint": node.output.taint.value,
                    "satisfied": satisfied,
                    "observed": observed,
                },
            )
        )
        return True

    async def _run_branch(self, node: BranchNode, outcome: ReplayOutcome, ctx: RuntimeContext) -> bool:
        satisfied = await evaluate_condition(node.condition, ctx, self._hooks)
        decision = "then" if satisfied else "else"
        ctx.branch_decisions[node.id] = decision
        outcome.visited_nodes.append(node.id)
        outcome.steps.append(
            StepRecord(node_id=node.id, kind="branch", status=decision, detail={"condition": satisfied})
        )
        children = node.then_nodes if satisfied else node.else_nodes
        for child in children:
            if not await self._run_node(child, outcome, ctx):
                return False
        return True

    async def _run_loop_node(self, node: LoopNode, outcome: ReplayOutcome, ctx: RuntimeContext) -> bool:
        outcome.visited_nodes.append(node.id)
        outcome.steps.append(
            StepRecord(node_id=node.id, kind="loop", status="started", detail={"max_iterations": node.max_iterations})
        )
        return await run_loop(node, ctx, self._hooks, lambda child: self._run_node(child, outcome, ctx))

    async def _run_action(self, node: ActionNode, outcome: ReplayOutcome, ctx: RuntimeContext) -> bool:
        scene_version = await self._hooks.current_scene_version()
        resolved_value = ctx.resolve_value(node.value)
        if node.value is not None and resolved_value is None:
            outcome.steps.append(
                StepRecord(
                    node_id=node.id,
                    kind="action",
                    status="capture_missing",
                    detail={"value_kind": node.value.kind},
                )
            )
            outcome.aborted_reason = f"capture_missing:{node.id}"
            outcome.aborted_node = node.id
            return False
        dispatch_node = node.model_copy(update={"value": resolved_value})
        healed_record: HealingRecord | None = None
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
                recovery = await self._attempt_recovery(node, scene, scene_version, outcome)
                if recovery is None:
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
                if recovery.recovered_target is None:
                    record = recovery.record
                    outcome.steps.append(
                        StepRecord(
                            node_id=node.id,
                            kind="action",
                            status="guard_rejected",
                            detail={
                                "code": decision.code.value if decision.code else None,
                                "reason": decision.reason,
                                "healing": {
                                    "opportunity_id": record.opportunity_id,
                                    "attempt_id": record.attempt_id,
                                    "decision": record.decision.value,
                                    "refusal_reason": record.refusal_reason,
                                },
                            },
                        )
                    )
                    outcome.aborted_reason = f"healing_refused:{record.refusal_reason or 'unknown'}"
                    outcome.aborted_node = node.id
                    return False
                healed_record = recovery.record
                recovered_target: TargetDescriptor = recovery.recovered_target
                dispatch_node = dispatch_node.model_copy(update={"target": recovered_target})
        result = await self._hooks.dispatch_action(dispatch_node, scene_version)
        step_status = "settled" if result.succeeded else result.state
        detail: dict[str, object] = {
            "command_id": str(result.command_id),
            "outcome": result.outcome,
            "evidence_refs": list(result.evidence_refs),
            "reason": result.reason,
        }
        if healed_record is not None:
            record = healed_record.model_copy(update={"dispatch_outcome": result.outcome})
            outcome.healing_records[-1] = record
            step_status = "healed" if result.succeeded else f"healed_{result.state}"
            detail["healing"] = {
                "opportunity_id": record.opportunity_id,
                "attempt_id": record.attempt_id,
                "actual_signature": record.actual_signature,
                "guard_checks": list(record.guard_checks),
            }
            if result.succeeded and node.postconditions:
                postconditions = await self._evaluate_postconditions(node)
                detail["postconditions"] = postconditions
                record = record.model_copy(
                    update={"postconditions_ok": all(postconditions.values()) if postconditions else None}
                )
                outcome.healing_records[-1] = record
                if not all(postconditions.values()):
                    await self._hooks.record_healing(record)
                    outcome.steps.append(StepRecord(node_id=node.id, kind="action", status=step_status, detail=detail))
                    outcome.visited_nodes.append(node.id)
                    outcome.aborted_reason = f"postcondition_failed:{node.id}"
                    outcome.aborted_node = node.id
                    return False
            await self._hooks.record_healing(record)
        outcome.steps.append(StepRecord(node_id=node.id, kind="action", status=step_status, detail=detail))
        outcome.visited_nodes.append(node.id)
        if not result.succeeded:
            outcome.aborted_reason = f"action_not_settled:{result.reason or result.outcome}"
            outcome.aborted_node = node.id
            return False
        return True

    async def _attempt_recovery(
        self,
        node: ActionNode,
        scene: list[SceneCandidate],
        scene_version: int,
        outcome: ReplayOutcome,
    ) -> HealDecision | None:
        if self._healer is None or node.target is None:
            return None
        decision = await self._healer.recover(
            node.target,
            scene,
            HealContext(
                node_id=node.id,
                actor=HealingActor.ACTION,
                operation=node.operation,
                frame_key=node.context.frame if node.context else None,
                scene_version=scene_version,
            ),
        )
        outcome.healing_records.append(decision.record)
        if decision.recovered_target is None:
            await self._hooks.record_healing(decision.record)
        return decision

    async def _evaluate_postconditions(self, node: ActionNode) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for name in node.postconditions:
            satisfied = await self._hooks.evaluate_postcondition(node, name)
            results[name] = bool(satisfied)
        return results

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
