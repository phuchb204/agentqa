from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from agentqa.contracts.case import BranchNode, CaseContent, CaseNode, CheckpointNode, LoopNode


@dataclass(frozen=True)
class CompletionPlan:
    required_nodes: tuple[str, ...]
    required_assertions: tuple[str, ...]
    assertion_checkpoints: Mapping[str, str] = field(default_factory=dict)
    branch_membership: Mapping[str, tuple[str, str]] = field(default_factory=dict)
    node_branches: Mapping[str, tuple[str, str]] = field(default_factory=dict)

    @classmethod
    def from_case(cls, case: CaseContent) -> CompletionPlan:
        assertion_checkpoints: dict[str, str] = {}
        branch_membership: dict[str, tuple[str, str]] = {}
        node_branches: dict[str, tuple[str, str]] = {}
        _walk(case.nodes, None, assertion_checkpoints, branch_membership, node_branches)
        return cls(
            required_nodes=tuple(case.completion.required_nodes),
            required_assertions=tuple(case.completion.required_assertions),
            assertion_checkpoints=assertion_checkpoints,
            branch_membership=branch_membership,
            node_branches=node_branches,
        )


def _walk(
    nodes: list[CaseNode],
    branch: tuple[str, str] | None,
    assertion_checkpoints: dict[str, str],
    branch_membership: dict[str, tuple[str, str]],
    node_branches: dict[str, tuple[str, str]],
) -> None:
    for node in nodes:
        if branch is not None:
            node_branches[node.id] = branch
        if isinstance(node, CheckpointNode):
            if branch is not None:
                branch_membership[node.id] = branch
            for assertion in node.assertions:
                assertion_checkpoints[assertion.id] = node.id
        elif isinstance(node, BranchNode):
            _walk(node.then_nodes, (node.id, "then"), assertion_checkpoints, branch_membership, node_branches)
            _walk(node.else_nodes, (node.id, "else"), assertion_checkpoints, branch_membership, node_branches)
        elif isinstance(node, LoopNode):
            _walk(node.body, branch, assertion_checkpoints, branch_membership, node_branches)


@dataclass(frozen=True)
class ExecutionProof:
    visited_nodes: frozenset[str] = frozenset()
    branch_decisions: Mapping[str, str] = field(default_factory=dict)
    checkpoint_receipts: frozenset[str] = frozenset()


@dataclass(frozen=True)
class CompletionOutcome:
    complete: bool
    proof_valid: bool
    missing_nodes: tuple[str, ...] = ()
    missing_receipts: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def completion_proof(self) -> str:
        return f"complete={self.complete};proof_valid={self.proof_valid}"


def evaluate_completion(plan: CompletionPlan, proof: ExecutionProof) -> CompletionOutcome:
    missing_nodes = tuple(
        node
        for node in plan.required_nodes
        if node not in proof.visited_nodes and not _node_branch_excludes(plan, proof, node)
    )
    required_checkpoints = {
        plan.assertion_checkpoints[assertion]
        for assertion in plan.required_assertions
        if assertion in plan.assertion_checkpoints
    }
    missing_receipts = tuple(
        sorted(
            checkpoint
            for checkpoint in required_checkpoints
            if checkpoint not in proof.checkpoint_receipts and not _branch_excludes(plan, proof, checkpoint)
        )
    )
    reasons: list[str] = []
    if missing_nodes:
        reasons.append("missing_required_nodes")
    if missing_receipts:
        reasons.append("missing_checkpoint_receipts")
    complete = not missing_nodes
    proof_valid = complete and not missing_receipts
    return CompletionOutcome(
        complete=complete,
        proof_valid=proof_valid,
        missing_nodes=missing_nodes,
        missing_receipts=missing_receipts,
        reasons=tuple(reasons),
    )


def _branch_excludes(plan: CompletionPlan, proof: ExecutionProof, checkpoint_id: str) -> bool:
    membership = plan.branch_membership.get(checkpoint_id)
    if membership is None:
        return False
    branch_id, side = membership
    decision = proof.branch_decisions.get(branch_id)
    return decision is not None and decision != side


def _node_branch_excludes(plan: CompletionPlan, proof: ExecutionProof, node_id: str) -> bool:
    membership = plan.node_branches.get(node_id)
    if membership is None:
        return False
    branch_id, side = membership
    decision = proof.branch_decisions.get(branch_id)
    return decision is not None and decision != side


def assertion_applicability(
    plan: CompletionPlan,
    proof: ExecutionProof,
    assertion_id: str,
) -> tuple[bool | None, str]:
    checkpoint_id = plan.assertion_checkpoints.get(assertion_id)
    if checkpoint_id is None:
        return None, "unknown_assertion"
    membership = plan.branch_membership.get(checkpoint_id)
    if membership is not None:
        branch_id, side = membership
        decision = proof.branch_decisions.get(branch_id)
        if decision is not None and decision != side:
            return False, "branch_not_taken"
    if checkpoint_id in proof.checkpoint_receipts:
        return True, "checkpoint_visited"
    if membership is not None and proof.branch_decisions.get(membership[0]) is None:
        return None, "not_evaluated_no_branch_proof"
    return None, "not_evaluated_checkpoint_missing"
