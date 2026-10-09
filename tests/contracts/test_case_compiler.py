from __future__ import annotations

from pathlib import Path

import pytest

from agentqa.contracts.compiler import MAX_DOCUMENT_BYTES, compile_case_document
from agentqa.contracts.errors import AgentQAValidationError, ErrorCode

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def error_codes(exc: AgentQAValidationError) -> set[ErrorCode]:
    return {error.code for error in exc.errors}


def test_valid_case_compiles_with_digest_and_checkpoint_link() -> None:
    compiled = compile_case_document(load_fixture("valid_case.yaml"))
    assert compiled.case.logical_key == "login_and_add_item"
    assert compiled.capabilities == ()
    assert len(compiled.content_digest) == 64
    checkpoint = compiled.case.nodes[-1]
    assert checkpoint.assertions[0].checkpoint_id == "result"


def test_minimal_case_uses_optional_defaults() -> None:
    compiled = compile_case_document(load_fixture("valid_case_minimal.yaml"))
    assert compiled.case.preconditions == []
    assert compiled.case.fixture_refs == []
    assert compiled.case.required_capabilities == []


def test_branch_case_compiles() -> None:
    compiled = compile_case_document(load_fixture("valid_branch_case.yaml"))
    assert "decide" in {node.id for node in compiled.case.nodes}


@pytest.mark.parametrize(
    ("fixture", "code"),
    [
        ("invalid_duplicate_keys.yaml", ErrorCode.DUPLICATE_KEY),
        ("malicious_import.yaml", ErrorCode.CUSTOM_TAG_REJECTED),
        ("invalid_unknown_node.yaml", ErrorCode.UNSUPPORTED_NODE),
        ("invalid_unknown_operation.yaml", ErrorCode.UNKNOWN_OPERATION),
        ("invalid_duplicate_ids.yaml", ErrorCode.DUPLICATE_ID),
        ("invalid_unsafe_capture.yaml", ErrorCode.INVALID_CAPTURE),
        ("invalid_secret_url.yaml", ErrorCode.SECRET_INTERPOLATION),
        ("invalid_secret_assertion.yaml", ErrorCode.SECRET_INTERPOLATION),
        ("invalid_empty_assertion.yaml", ErrorCode.EMPTY_ASSERTION),
        ("invalid_inferred_unconfirmed.yaml", ErrorCode.SOURCE_UNCONFIRMED),
        ("invalid_branch_proof.yaml", ErrorCode.INCOMPLETE_BRANCH_PROOF),
        ("invalid_loop_bound.yaml", ErrorCode.LOOP_BOUND_INVALID),
        ("invalid_capability.yaml", ErrorCode.CAPABILITY_MISMATCH),
        ("invalid_parameter_type.yaml", ErrorCode.TYPE_MISMATCH),
    ],
)
def test_invalid_fixtures_are_rejected_with_code(fixture: str, code: ErrorCode) -> None:
    with pytest.raises(AgentQAValidationError) as excinfo:
        compile_case_document(load_fixture(fixture))
    assert code in error_codes(excinfo.value)


def test_capture_error_carries_field_path() -> None:
    with pytest.raises(AgentQAValidationError) as excinfo:
        compile_case_document(load_fixture("invalid_unsafe_capture.yaml"))
    capture_errors = [error for error in excinfo.value.errors if error.code == ErrorCode.INVALID_CAPTURE]
    assert capture_errors
    assert capture_errors[0].path == ("nodes", 1, "assertions", 0, "expected")


def test_inferred_source_passes_when_confirmed_digest_supplied() -> None:
    text = load_fixture("invalid_inferred_unconfirmed.yaml")
    digest = "c" * 64
    compiled = compile_case_document(text, confirmed_source_digests=frozenset({digest}))
    assert compiled.case.logical_key == "inferred_unconfirmed"


def test_inferred_source_fails_without_confirmation() -> None:
    with pytest.raises(AgentQAValidationError) as excinfo:
        compile_case_document(load_fixture("invalid_inferred_unconfirmed.yaml"))
    assert ErrorCode.SOURCE_UNCONFIRMED in error_codes(excinfo.value)


def test_oversized_document_rejected() -> None:
    with pytest.raises(AgentQAValidationError) as excinfo:
        compile_case_document("a: " + "b" * MAX_DOCUMENT_BYTES)
    assert ErrorCode.DOCUMENT_TOO_LARGE in error_codes(excinfo.value)


def test_alias_bomb_rejected() -> None:
    document = "anchor: &a [1]\nrefs: [" + ", ".join(["*a"] * 33) + "]\n"
    with pytest.raises(AgentQAValidationError) as excinfo:
        compile_case_document(document)
    assert ErrorCode.ALIAS_LIMIT_EXCEEDED in error_codes(excinfo.value)
