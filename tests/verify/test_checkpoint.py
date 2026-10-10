from __future__ import annotations

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.verification import AssertionStatus, Comparator, EvidenceRequirement, EvidenceStatus, WaitPolicy
from agentqa.verify import evaluate_checkpoint
from tests.verify.conftest import (
    FakeClock,
    FakeFacts,
    assertion,
    checkpoint_request,
    entity_scope,
    parameter_expected,
    target,
)


def test_visible_absent_and_count_assertions() -> None:
    facts = FakeFacts(counts={"rows": 2}, visibles={"banner": True, "ghost": False}, texts={"banner": "Xin chào"})
    results = evaluate_checkpoint(
        checkpoint_request(
            [
                assertion("banner_visible", Comparator.VISIBLE, target_descriptor=target("banner"), expected=True),
                assertion("ghost_visible", Comparator.VISIBLE, target_descriptor=target("ghost"), expected=True),
                assertion("missing_absent", Comparator.EXISTS, target_descriptor=target("missing"), expected=False),
                assertion("two_rows", Comparator.COUNT_EQUALS, target_descriptor=target("rows"), expected=2),
                assertion(
                    "at_least_two", Comparator.COUNT_GREATER_OR_EQUAL, target_descriptor=target("rows"), expected=2
                ),
                assertion("unique_row", Comparator.UNIQUE, target_descriptor=target("rows")),
            ]
        ),
        facts,
    )
    statuses = {result.assertion_id: result.status for result in results}
    assert statuses["banner_visible"] == AssertionStatus.PASSED
    assert statuses["ghost_visible"] == AssertionStatus.FAILED
    assert statuses["missing_absent"] == AssertionStatus.PASSED
    assert statuses["two_rows"] == AssertionStatus.PASSED
    assert statuses["at_least_two"] == AssertionStatus.PASSED
    assert statuses["unique_row"] == AssertionStatus.FAILED
    assert results[0].observed_redacted == "True"


def test_text_url_value_and_attribute_assertions() -> None:
    facts = FakeFacts(
        url="http://fixture.example/tasks?page=2",
        texts={"title": "Danh sách việc", "count": "3"},
        attributes={("row", "data-item-id"): "item-2"},
    )
    results = evaluate_checkpoint(
        checkpoint_request(
            [
                assertion(
                    "title_ok", Comparator.TEXT_EQUALS, target_descriptor=target("title"), expected="Danh sách việc"
                ),
                assertion("title_contains", Comparator.CONTAINS, target_descriptor=target("title"), expected="việc"),
                assertion("title_wrong", Comparator.TEXT_EQUALS, target_descriptor=target("title"), expected="Sai"),
                assertion("url_path", Comparator.URL_PATH_EQUALS, expected="/tasks"),
                assertion(
                    "attr_ok",
                    Comparator.ATTRIBUTE_EQUALS,
                    target_descriptor=target("row", attributes={"data-item-id": "item-2"}),
                    expected="item-2",
                ),
                assertion(
                    "attr_wrong",
                    Comparator.ATTRIBUTE_EQUALS,
                    target_descriptor=target("row", attributes={"data-item-id": "item-2"}),
                    expected="item-9",
                ),
                assertion("missing_text", Comparator.TEXT_EQUALS, target_descriptor=target("nope"), expected="x"),
            ]
        ),
        facts,
    )
    statuses = {result.assertion_id: result.status for result in results}
    assert statuses["title_ok"] == AssertionStatus.PASSED
    assert statuses["title_contains"] == AssertionStatus.PASSED
    assert statuses["title_wrong"] == AssertionStatus.FAILED
    assert statuses["url_path"] == AssertionStatus.PASSED
    assert statuses["attr_ok"] == AssertionStatus.PASSED
    assert statuses["attr_wrong"] == AssertionStatus.FAILED
    assert statuses["missing_text"] == AssertionStatus.FAILED
    assert {result.evidence_status for result in results} == {EvidenceStatus.PRESENT}


def test_entity_scope_count_matches_expected_outcome() -> None:
    facts = FakeFacts(counts={"row": 1})
    results = evaluate_checkpoint(
        checkpoint_request(
            [
                assertion(
                    "item_exists_once",
                    Comparator.COUNT_EQUALS,
                    target_descriptor=target("row", role="listitem", entity_scope=entity_scope("Việc A")),
                    expected=1,
                )
            ]
        ),
        facts,
    )
    assert results[0].status == AssertionStatus.PASSED


def test_wait_policy_polls_read_only_until_condition_holds() -> None:
    facts = FakeFacts(counts={"rows": 0})
    clock = FakeClock()

    def sleep(seconds: float) -> None:
        clock.now += seconds
        if clock.now >= 0.2:
            facts.set_count("rows", 1)

    results = evaluate_checkpoint(
        checkpoint_request(
            [
                assertion(
                    "eventually_once",
                    Comparator.COUNT_EQUALS,
                    target_descriptor=target("rows"),
                    expected=1,
                    wait=WaitPolicy(timeout_ms=2000, poll_ms=50),
                )
            ]
        ),
        facts,
        clock=clock,
        sleep=sleep,
    )
    assert results[0].status == AssertionStatus.PASSED
    assert results[0].observed_redacted == "1"


def test_wait_policy_timeout_reports_failed_with_last_observation() -> None:
    facts = FakeFacts(counts={"rows": 0})
    clock = FakeClock()

    def sleep(seconds: float) -> None:
        clock.now += seconds

    results = evaluate_checkpoint(
        checkpoint_request(
            [
                assertion(
                    "never",
                    Comparator.COUNT_EQUALS,
                    target_descriptor=target("rows"),
                    expected=1,
                    wait=WaitPolicy(timeout_ms=300, poll_ms=50),
                )
            ]
        ),
        facts,
        clock=clock,
        sleep=sleep,
    )
    assert results[0].status == AssertionStatus.FAILED
    assert results[0].observed_redacted == "0"


def test_unresolved_expected_expression_is_error_not_pass() -> None:
    facts = FakeFacts(counts={"rows": 1})
    results = evaluate_checkpoint(
        checkpoint_request(
            [
                assertion(
                    "parameter_expected",
                    Comparator.COUNT_EQUALS,
                    target_descriptor=target("rows"),
                    expected_expr=parameter_expected(),
                )
            ]
        ),
        facts,
    )
    assert results[0].status == AssertionStatus.ERROR
    assert results[0].reason == ErrorCode.INPUT_INVALID.value


def test_missing_required_evidence_is_error_not_business_failure() -> None:
    facts = FakeFacts(
        counts={"rows": 0},
        evidence={"needs_evidence": EvidenceStatus.MISSING},
    )
    results = evaluate_checkpoint(
        checkpoint_request(
            [
                assertion(
                    "needs_evidence",
                    Comparator.COUNT_EQUALS,
                    target_descriptor=target("rows"),
                    expected=1,
                    required=True,
                    evidence=EvidenceRequirement.REQUIRED,
                ),
                assertion(
                    "optional_evidence",
                    Comparator.COUNT_EQUALS,
                    target_descriptor=target("rows"),
                    expected=0,
                    required=False,
                    evidence=EvidenceRequirement.OPTIONAL,
                ),
            ]
        ),
        facts,
    )
    statuses = {result.assertion_id: result.status for result in results}
    assert statuses["needs_evidence"] == AssertionStatus.ERROR
    assert results[0].reason == ErrorCode.EVIDENCE_MISSING.value
    assert results[0].evidence_status == EvidenceStatus.MISSING
    assert statuses["optional_evidence"] == AssertionStatus.PASSED


def test_redaction_failure_is_error_not_failure() -> None:
    facts = FakeFacts(
        counts={"rows": 1},
        evidence={"masked": EvidenceStatus.REDACTION_FAILED},
    )
    results = evaluate_checkpoint(
        checkpoint_request(
            [
                assertion(
                    "masked",
                    Comparator.COUNT_EQUALS,
                    target_descriptor=target("rows"),
                    expected=1,
                )
            ]
        ),
        facts,
    )
    assert results[0].status == AssertionStatus.ERROR
    assert results[0].reason == ErrorCode.EVIDENCE_REDACTION_FAILED.value
