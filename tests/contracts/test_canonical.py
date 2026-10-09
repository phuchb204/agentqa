from __future__ import annotations

import json
import struct
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from agentqa.contracts.canonical import (
    FrozenMapping,
    canonicalize,
    digest_artifact_bytes,
    digest_content,
    digest_run_snapshot,
    freeze,
)
from agentqa.contracts.compiler import compile_case_document
from agentqa.contracts.errors import AgentQAValidationError, ErrorCode
from agentqa.contracts.runs import RevisionLifecycle, RevisionRecord
from agentqa.contracts.values import Money

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"

RFC_8785_PRIMITIVE_HEX = (
    "7b226c69746572616c73223a5b6e756c6c2c747275652c66616c73655d2c226e756d62657273223a5b"
    + "33" * 9
    + "2e"
    + "33" * 7
    + "2c31652b33302c342e352c302e3030322c31652d32375d2c22737472696e67223a22"
    + "e282ac245c75303030665c6e4127425c225c5c5c5c5c222f227d"
)

RFC_8785_SOURCE = {
    "numbers": [333333333.33333329, 1e30, 4.5, 2e-3, 1e-27],
    "string": '\u20ac$\x0f\nA\'B"\\\\"/',
    "literals": [None, True, False],
}


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_rfc8785_primitive_vector_matches_rfc_bytes() -> None:
    assert canonicalize(RFC_8785_SOURCE).hex() == RFC_8785_PRIMITIVE_HEX


def test_rfc8785_property_sorting_order() -> None:
    source = {
        "\u20ac": "Euro Sign",
        "\r": "Carriage Return",
        "\ufb33": "Hebrew Letter Dalet With Dagesh",
        "1": "One",
        "\U0001f600": "Emoji: Grinning Face",
        "\u0080": "Control",
        "\u00f6": "Latin Small Letter O With Diaeresis",
    }
    expected_order = [
        "Carriage Return",
        "One",
        "Control",
        "Latin Small Letter O With Diaeresis",
        "Euro Sign",
        "Emoji: Grinning Face",
        "Hebrew Letter Dalet With Dagesh",
    ]
    decoded = json.loads(canonicalize(source).decode("utf-8"))
    assert list(decoded.values()) == expected_order


NUMBER_SAMPLES = [
    ("0000000000000000", b"0"),
    ("8000000000000000", b"0"),
    ("0000000000000001", b"5e-324"),
    ("7fefffffffffffff", b"1.7976931348623157e+308"),
    ("4340000000000000", b"9007199254740992"),
    ("4430000000000000", b"295147905179352830000"),
    ("44b52d02c7e14af6", b"1e+23"),
    ("3eb0c6f7a0b5ed8d", b"0.000001"),
    ("41b3de4355555555", b"333333333.3333333"),
    ("becbf647612f3696", b"-0.0000033333333333333333"),
    ("43143ff3c1cb0959", b"1424953923781206.2"),
]


@pytest.mark.parametrize(("ieee_hex", "expected"), NUMBER_SAMPLES)
def test_rfc8785_number_samples(ieee_hex: str, expected: bytes) -> None:
    value = struct.unpack(">d", bytes.fromhex(ieee_hex))[0]
    assert canonicalize(value) == expected


def test_digest_domains_are_separated() -> None:
    compiled = compile_case_document(load_fixture("valid_case.yaml"))
    content = digest_content(compiled.case)
    snapshot = digest_run_snapshot(compiled.case)
    artifact = digest_artifact_bytes(canonicalize(compiled.case))
    assert content != snapshot
    assert content != artifact
    assert len({content, snapshot, artifact}) == 3


def test_content_digest_ignores_revision_metadata() -> None:
    compiled = compile_case_document(load_fixture("valid_case.yaml"))
    first = RevisionRecord(
        workspace_id=uuid4(),
        entity_id=uuid4(),
        revision_id=uuid4(),
        content=compiled.case,
        content_digest=compiled.content_digest,
        lifecycle=RevisionLifecycle.DRAFT,
        author="author-a",
    )
    second = RevisionRecord(
        workspace_id=uuid4(),
        entity_id=uuid4(),
        revision_id=uuid4(),
        content=compiled.case,
        content_digest="f" * 64,
        lifecycle=RevisionLifecycle.ARCHIVED,
        author="author-b",
        promoted_by="owner",
    )
    assert digest_content(first.content) == digest_content(second.content) == compiled.content_digest


def test_content_digest_is_stable_across_roundtrip() -> None:
    compiled = compile_case_document(load_fixture("valid_case.yaml"))
    reparsed = type(compiled.case).model_validate(compiled.case.model_dump())
    assert digest_content(reparsed) == compiled.content_digest


def test_money_serializes_as_decimal_string() -> None:
    money = Money(amount=Decimal("1234.50"), currency="USD")
    assert canonicalize(money) == b'{"amount":"1234.50","currency":"USD"}'
    assert money.model_dump(mode="json")["amount"] == "1234.50"


def test_money_rejects_float() -> None:
    with pytest.raises(ValueError):
        Money(amount=12.5, currency="USD")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 2**53, -(2**53)])
def test_unsafe_json_values_rejected(value: float) -> None:
    with pytest.raises(AgentQAValidationError) as excinfo:
        canonicalize({"value": value})
    assert ErrorCode.UNSAFE_JSON in {error.code for error in excinfo.value.errors}


def test_freeze_blocks_nested_mutation() -> None:
    frozen = freeze({"outer": {"inner": [{"leaf": 1}]}})
    assert isinstance(frozen, FrozenMapping)
    assert frozen["outer"]["inner"][0]["leaf"] == 1
    with pytest.raises(TypeError):
        frozen["outer"]["inner"][0]["leaf"] = 2
    with pytest.raises(TypeError):
        frozen["outer"] = {}
    with pytest.raises(TypeError):
        frozen["outer"]["inner"][0]["new"] = "x"
