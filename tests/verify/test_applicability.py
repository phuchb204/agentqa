from __future__ import annotations

from agentqa.contracts.case import CaseContent
from agentqa.verify import (
    CompletionPlan,
    ExecutionProof,
    assertion_applicability,
    evaluate_completion,
)


def branch_case() -> CaseContent:
    return CaseContent.model_validate(
        {
            "schema_version": "case/1",
            "logical_key": "branch_case",
            "title": "Branch case",
            "goal": "Kiểm tra nhánh",
            "requirements": ["r1"],
            "nodes": [
                {
                    "id": "branch-1",
                    "kind": "branch",
                    "condition": {
                        "kind": "comparison",
                        "comparator": "exists",
                        "target": {"intent": "condition"},
                    },
                    "then_nodes": [
                        {
                            "id": "check-then",
                            "kind": "checkpoint",
                            "assertions": [
                                {
                                    "id": "then_assertion",
                                    "comparator": "exists",
                                    "target": {"intent": "then"},
                                    "required": True,
                                    "source_refs": ["r1"],
                                }
                            ],
                        }
                    ],
                    "else_nodes": [
                        {
                            "id": "check-else",
                            "kind": "checkpoint",
                            "assertions": [
                                {
                                    "id": "else_assertion",
                                    "comparator": "exists",
                                    "target": {"intent": "else"},
                                    "required": True,
                                    "source_refs": ["r1"],
                                }
                            ],
                        }
                    ],
                }
            ],
            "completion": {"required_nodes": ["branch-1"], "required_assertions": []},
        }
    )


def manual_plan() -> CompletionPlan:
    return CompletionPlan(
        required_nodes=("add_item", "result"),
        required_assertions=("item_exists_once",),
        assertion_checkpoints={"item_exists_once": "result", "else_only": "check-else"},
        branch_membership={"check-else": ("branch-1", "else"), "result": ("branch-1", "then")},
    )


def test_branch_guard_proves_not_applicable() -> None:
    plan = manual_plan()
    proof = ExecutionProof(branch_decisions={"branch-1": "then"})
    applicable, reason = assertion_applicability(plan, proof, "else_only")
    assert applicable is False
    assert reason == "branch_not_taken"


def test_unvisited_required_checkpoint_is_not_evaluated_not_skipped() -> None:
    plan = manual_plan()
    proof = ExecutionProof()
    applicable, reason = assertion_applicability(plan, proof, "item_exists_once")
    assert applicable is None
    assert reason == "not_evaluated_no_branch_proof"


def test_visited_checkpoint_is_applicable() -> None:
    plan = manual_plan()
    proof = ExecutionProof(branch_decisions={"branch-1": "then"}, checkpoint_receipts=frozenset({"result"}))
    applicable, reason = assertion_applicability(plan, proof, "item_exists_once")
    assert applicable is True
    assert reason == "checkpoint_visited"


def test_completion_requires_nodes_and_checkpoint_receipts() -> None:
    plan = manual_plan()
    missing = evaluate_completion(plan, ExecutionProof(visited_nodes=frozenset({"add_item"})))
    assert missing.complete is False
    assert missing.proof_valid is False
    assert missing.missing_nodes == ("result",)
    assert missing.missing_receipts == ("result",)

    complete = evaluate_completion(
        plan,
        ExecutionProof(
            visited_nodes=frozenset({"add_item", "result"}),
            checkpoint_receipts=frozenset({"result"}),
        ),
    )
    assert complete.complete is True
    assert complete.proof_valid is True
    assert complete.reasons == ()


def test_from_case_walks_branch_membership() -> None:
    plan = CompletionPlan.from_case(branch_case())
    assert plan.assertion_checkpoints == {"then_assertion": "check-then", "else_assertion": "check-else"}
    assert plan.branch_membership == {
        "check-then": ("branch-1", "then"),
        "check-else": ("branch-1", "else"),
    }
