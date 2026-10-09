from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agentqa.contracts.compiler import compile_case_document
from agentqa.contracts.errors import (
    AgentQAValidationError,
    ErrorCode,
    FieldError,
    ensure_known_schema_version,
    parse_schema_version,
    upcast_document,
)
from agentqa.contracts.events import EventType, RunEvent, RunStateChangedPayload
from agentqa.contracts.runs import ExecutionStatus

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"


def test_known_schema_versions_accepted() -> None:
    ensure_known_schema_version("case/1")
    ensure_known_schema_version("run-event/1")
    assert parse_schema_version("case/1") == ("case", "1")


@pytest.mark.parametrize("version", ["case/2", "case/0", "run-event/9", "other/1"])
def test_unknown_schema_versions_rejected(version: str) -> None:
    with pytest.raises(AgentQAValidationError) as excinfo:
        ensure_known_schema_version(version)
    assert ErrorCode.UNSUPPORTED_SCHEMA_VERSION in {error.code for error in excinfo.value.errors}
    assert excinfo.value.errors[0].path == ("schema_version",)


@pytest.mark.parametrize("version", ["case", "case/1/2", "/1", "case/"])
def test_malformed_schema_versions_rejected(version: str) -> None:
    with pytest.raises(AgentQAValidationError) as excinfo:
        ensure_known_schema_version(version)
    assert ErrorCode.UNSUPPORTED_SCHEMA_VERSION in {error.code for error in excinfo.value.errors}


def test_upcast_returns_detached_copy() -> None:
    document = {"a": 1}
    upgraded = upcast_document("case/1", document)
    upgraded["a"] = 2
    assert document["a"] == 1


def test_case_document_with_unknown_version_is_rejected() -> None:
    text = (FIXTURES / "valid_case.yaml").read_text(encoding="utf-8").replace("case/1", "case/2", 1)
    with pytest.raises(AgentQAValidationError) as excinfo:
        compile_case_document(text)
    assert ErrorCode.UNSUPPORTED_SCHEMA_VERSION in {error.code for error in excinfo.value.errors}


def test_field_error_envelope_shape() -> None:
    error = FieldError(path=("nodes", 0, "id"), code=ErrorCode.DUPLICATE_ID, message="trùng")
    dumped = error.model_dump(mode="json")
    assert set(dumped) == {"path", "code", "message"}
    assert dumped["code"] == "duplicate_id"
    assert dumped["path"] == ["nodes", 0, "id"]


def test_error_messages_do_not_echo_input_values() -> None:
    document = (
        "schema_version: case/1\n"
        "logical_key: canary\n"
        "title: x\n"
        "goal: y\n"
        "parameter_defs:\n"
        "  p: {type: canary-secret-value}\n"
        "nodes:\n"
        "  - id: n\n"
        "    kind: action\n"
        "    operation: click\n"
        "    side_effect: read\n"
        "completion: {required_nodes: [n]}\n"
    )
    with pytest.raises(AgentQAValidationError) as excinfo:
        compile_case_document(document)
    assert "canary-secret-value" not in str(excinfo.value)


def test_run_event_version_is_pinned() -> None:
    payload = RunStateChangedPayload(event_type=EventType.RUN_STATE_CHANGED, status=ExecutionStatus.QUEUED)
    event = RunEvent(
        event_id=uuid4(),
        run_id=uuid4(),
        run_seq=1,
        schema_version="run-event/1",
        type=EventType.RUN_STATE_CHANGED,
        actor="test",
        payload=payload,
        recorded_at=datetime.now(UTC),
    )
    assert event.schema_version == "run-event/1"
    with pytest.raises(ValidationError):
        RunEvent(
            event_id=uuid4(),
            run_id=uuid4(),
            run_seq=1,
            schema_version="run-event/2",
            type=EventType.RUN_STATE_CHANGED,
            actor="test",
            payload=payload,
            recorded_at=datetime.now(UTC),
        )


def test_run_event_payload_must_match_type() -> None:
    with pytest.raises(AgentQAValidationError):
        RunEvent(
            event_id=uuid4(),
            run_id=uuid4(),
            run_seq=1,
            type=EventType.RUN_FINALIZED,
            actor="test",
            payload=RunStateChangedPayload(event_type=EventType.RUN_STATE_CHANGED, status=ExecutionStatus.QUEUED),
            recorded_at=datetime.now(UTC),
        )
