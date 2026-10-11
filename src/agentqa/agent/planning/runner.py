from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from agentqa.agent.history import ActionHistory, HistoryEntry
from agentqa.agent.planning.observation import AgentObservation
from agentqa.agent.planning.planner import PlanningPlan, build_plan
from agentqa.agent.policies.values import ValueResolutionError, ValueResolver
from agentqa.agent.replay.runner import ActionOutcomeView, StepRecord
from agentqa.contracts.actions import Operation, SideEffectClass
from agentqa.contracts.canonical import digest_content
from agentqa.contracts.case import ActionNode, CaseContent
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.policies import PolicyOutcome, PolicyProfile, ProposalKind
from agentqa.contracts.verification import AssertionResult

READ_OPERATIONS = frozenset(
    {
        Operation.NAVIGATE,
        Operation.WAIT,
        Operation.SCROLL,
        Operation.SWITCH_PAGE,
        Operation.SWITCH_FRAME,
        Operation.EXPECT_DOWNLOAD,
        Operation.HANDLE_DIALOG,
    }
)

FILL_OPERATIONS = frozenset({Operation.FILL, Operation.TYPE, Operation.CLEAR, Operation.SELECT, Operation.UPLOAD})


class AgentHooks(Protocol):
    async def observe(self) -> AgentObservation: ...

    async def dispatch(self, action: ActionNode, scene_version: int) -> ActionOutcomeView: ...

    async def evaluate_checkpoints(self) -> list[tuple[str, list[AssertionResult]]]: ...

    async def record_trace(self, label: str) -> str: ...


class AgentPolicy(Protocol):
    async def propose(
        self,
        *,
        observation: AgentObservation,
        plan: PlanningPlan,
        history: ActionHistory,
    ) -> PolicyOutcome: ...


@dataclass
class AgentRunOutcome:
    status: str
    steps: list[StepRecord] = field(default_factory=list)
    visited_nodes: list[str] = field(default_factory=list)
    checkpoint_receipts: set[str] = field(default_factory=set)
    assertion_results: list[AssertionResult] = field(default_factory=list)
    trace_refs: list[str] = field(default_factory=list)
    aborted_reason: str | None = None
    aborted_node: str | None = None
    degraded: bool = False
    policy_versions: list[str] = field(default_factory=list)
    rejections: int = 0
    generated_values: int = 0


class AgentRunner:
    def __init__(
        self,
        case: CaseContent,
        *,
        hooks: AgentHooks,
        policy: AgentPolicy,
        profile: PolicyProfile,
        value_resolver: ValueResolver | None = None,
        history: ActionHistory | None = None,
        parameters: dict[str, str] | None = None,
        captures: dict[str, str] | None = None,
    ) -> None:
        self._case = case
        self._hooks = hooks
        self._policy = policy
        self._profile = profile
        self._resolver = value_resolver or ValueResolver()
        self._history = history or ActionHistory(run_snapshot_digest=digest_content(case))
        self._parameters = dict(parameters or {})
        self._captures = dict(captures or {})

    @property
    def history(self) -> ActionHistory:
        return self._history

    async def run(self) -> AgentRunOutcome:
        plan = build_plan(self._case)
        outcome = AgentRunOutcome(status="succeeded")
        evaluated_any = False
        for step in range(1, self._profile.max_steps + 1):
            observation = await self._hooks.observe()
            policy_result = await self._policy.propose(
                observation=observation,
                plan=plan,
                history=self._history,
            )
            if policy_result.policy_version:
                outcome.policy_versions.append(policy_result.policy_version)
            if policy_result.degraded:
                outcome.degraded = True
            stopped = self._apply_stop(outcome, policy_result)
            if stopped is not None:
                return await self._finalize(outcome, evaluated_any)
            proposal = policy_result.proposal
            if proposal is None:
                outcome.aborted_reason = f"policy_failed:{policy_result.reason or 'unknown'}"
                return await self._finalize(outcome, evaluated_any)
            candidate = observation.candidate(proposal.candidate_id) if proposal.candidate_id else None
            if proposal.operation.needs_target() and candidate is None:
                outcome.rejections += 1
                outcome.steps.append(
                    StepRecord(
                        node_id=f"agent-step-{step}",
                        kind="proposal",
                        status="guard_rejected",
                        detail={"reason": "candidate_unknown"},
                    )
                )
                if outcome.rejections >= self._profile.stuck_after:
                    outcome.aborted_reason = "proposal_rejected:candidate_unknown"
                    return await self._finalize(outcome, evaluated_any)
                continue
            if candidate is not None and (not candidate.visible or candidate.actionability.value == "disabled"):
                outcome.rejections += 1
                outcome.steps.append(
                    StepRecord(
                        node_id=f"agent-step-{step}",
                        kind="proposal",
                        status="guard_rejected",
                        detail={"reason": "candidate_not_actionable", "candidate": candidate.candidate_id},
                    )
                )
                if outcome.rejections >= self._profile.stuck_after:
                    outcome.aborted_reason = "proposal_rejected:candidate_not_actionable"
                    return await self._finalize(outcome, evaluated_any)
                continue
            node = match_case_node(self._case, proposal.operation, proposal.target_intent, candidate)
            value, resolution_source = await self._resolve_value(node, proposal, candidate)
            if isinstance(value, str):
                outcome.aborted_reason = f"value_resolution_failed:{value}"
                return await self._finalize(outcome, evaluated_any)
            if resolution_source == "generated":
                outcome.generated_values += 1
            action = ActionNode(
                kind="action",
                id=node.id if node is not None else f"agent-step-{step}",
                operation=proposal.operation,
                target=node.target if node is not None else descriptor_for(candidate),
                value=value,
                side_effect=node.side_effect if node is not None else default_side_effect(proposal.operation),
                postconditions=list(node.postconditions) if node is not None else [],
            )
            view = await self._hooks.dispatch(action, observation.scene_version)
            step_status = "settled" if view.succeeded else view.state
            outcome.steps.append(
                StepRecord(
                    node_id=action.id,
                    kind="action",
                    status=step_status,
                    detail={
                        "command_id": str(view.command_id),
                        "outcome": view.outcome,
                        "reason": view.reason,
                        "candidate": proposal.candidate_id,
                        "resolved_value_source": resolution_source,
                    },
                )
            )
            self._history.record(
                HistoryEntry(
                    step=step,
                    operation=proposal.operation.value,
                    target_intent=proposal.target_intent,
                    outcome="succeeded" if view.succeeded else "failed",
                    reason=view.reason,
                    scene_version=observation.scene_version,
                )
            )
            if node is not None:
                outcome.visited_nodes.append(node.id)
            if not view.succeeded:
                reason = view.reason or view.outcome
                if (
                    self._history.failure_count(
                        operation=proposal.operation.value,
                        target_intent=proposal.target_intent,
                        reason=reason,
                    )
                    >= self._profile.stuck_after
                ):
                    outcome.aborted_reason = f"stuck:{reason}"
                    outcome.aborted_node = action.id
                    return await self._finalize(outcome, evaluated_any)
            else:
                outcome.rejections = 0
            evaluated_any = await self._collect_checkpoints(outcome)
        outcome.aborted_reason = "step_budget_exhausted"
        return await self._finalize(outcome, evaluated_any)

    def _apply_stop(self, outcome: AgentRunOutcome, result: PolicyOutcome) -> str | None:
        if result.kind is ProposalKind.STOP:
            outcome.aborted_reason = f"policy_stop:{result.reason}"
            return outcome.aborted_reason
        if result.kind is ProposalKind.NEED_CONTEXT:
            outcome.aborted_reason = "need_more_context"
            return outcome.aborted_reason
        if result.kind is ProposalKind.LOW_CONFIDENCE:
            outcome.aborted_reason = "policy_low_confidence"
            return outcome.aborted_reason
        if result.kind is ProposalKind.MALFORMED:
            outcome.aborted_reason = f"policy_malformed:{result.reason}"
            return outcome.aborted_reason
        if result.kind is ProposalKind.FAILED:
            outcome.aborted_reason = f"policy_failed:{result.reason}"
            return outcome.aborted_reason
        return None

    async def _resolve_value(self, node: ActionNode | None, proposal, candidate):
        operation = proposal.operation
        node_value = node.value if node is not None else None
        if operation in FILL_OPERATIONS:
            try:
                receipt = await self._resolver.resolve(
                    node_value=node_value,
                    proposal_value=proposal.value,
                    parameters=self._parameters,
                    captures=self._captures,
                    target_intent=(node.target.intent if node is not None and node.target else proposal.target_intent),
                )
            except ValueResolutionError as error:
                return (error.reason, "error")
            return (receipt.expr, receipt.source)
        if operation is Operation.PRESS:
            value = node_value if node_value is not None else proposal.value
            if value is None:
                return ("press_value_missing", "error")
            return (value, "node" if node_value is not None else "proposal")
        if operation is Operation.NAVIGATE:
            value = node_value if node_value is not None else proposal.value
            if value is None:
                return ("navigate_value_missing", "error")
            return (value, "node" if node_value is not None else "proposal")
        return (node_value, "node" if node_value is not None else "none")

    async def _collect_checkpoints(self, outcome: AgentRunOutcome) -> bool:
        evaluations = await self._hooks.evaluate_checkpoints()
        if not evaluations:
            return False
        latest: dict[str, AssertionResult] = {result.assertion_id: result for result in outcome.assertion_results}
        for node_id, results in evaluations:
            outcome.checkpoint_receipts.add(node_id)
            if node_id not in outcome.visited_nodes:
                outcome.visited_nodes.append(node_id)
            for result in results:
                latest[result.assertion_id] = result
        outcome.assertion_results = list(latest.values())
        return True

    async def _finalize(self, outcome: AgentRunOutcome, evaluated_any: bool) -> AgentRunOutcome:
        if not evaluated_any:
            await self._collect_checkpoints(outcome)
        if outcome.aborted_reason is not None:
            outcome.status = "error"
        return outcome


def match_case_node(
    case: CaseContent,
    operation: Operation,
    target_intent: str | None,
    candidate,
) -> ActionNode | None:
    for node in case.nodes:
        if not isinstance(node, ActionNode) or node.operation != operation:
            continue
        if target_intent and node.target is not None and node.target.intent == target_intent:
            return node
        if candidate is not None and node.target is not None:
            if node.target.name and node.target.name == candidate.name:
                return node
            if node.target.role and node.target.role == candidate.role and not node.target.name:
                return node
            if candidate.name and any(locator.value == candidate.name for locator in node.target.locators):
                return node
    return None


def descriptor_for(candidate) -> TargetDescriptor | None:
    if candidate is None:
        return None
    return TargetDescriptor(
        intent=f"agent:{candidate.role}:{candidate.name}"[:80],
        role=candidate.role or None,
        name=candidate.name or None,
    )


def default_side_effect(operation: Operation) -> SideEffectClass:
    if operation in READ_OPERATIONS:
        return SideEffectClass.READ
    return SideEffectClass.REVERSIBLE
