from __future__ import annotations

import json
import pickle

import pytest
from pydantic import ValidationError

from agentqa.contracts.values import (
    CaptureSegment,
    LiteralSegment,
    ParameterSegment,
    SecretValue,
    SensitiveValue,
    StringTemplate,
    Taint,
)

CANARY = "canary-secret-value"


def test_sensitive_value_does_not_leak_in_repr_or_str() -> None:
    secret = SensitiveValue(CANARY)
    assert CANARY not in repr(secret)
    assert CANARY not in str(secret)
    assert secret.reveal() == CANARY


def test_sensitive_value_has_no_serialization_path() -> None:
    secret = SensitiveValue(CANARY)
    with pytest.raises(TypeError):
        json.dumps({"value": secret})
    with pytest.raises(TypeError):
        pickle.dumps(secret)
    with pytest.raises(AttributeError):
        secret._value = "other"


def test_secret_value_expr_only_holds_reference() -> None:
    expr = SecretValue(kind="secret", credential_ref="demo_login.password")
    dumped = expr.model_dump(mode="json")
    assert dumped == {"kind": "secret", "credential_ref": "demo_login.password"}
    assert CANARY not in json.dumps(dumped)


def test_template_has_no_secret_segment() -> None:
    with pytest.raises(ValidationError):
        StringTemplate.model_validate({"segments": [{"kind": "secret", "credential_ref": "demo_login.password"}]})


def test_template_renders_only_declared_segments() -> None:
    template = StringTemplate(
        segments=[
            LiteralSegment(kind="literal", text="/items/"),
            ParameterSegment(kind="parameter", name="item_id"),
            CaptureSegment(kind="capture", name="token"),
        ]
    )
    assert template.render({"item_id": "42"}, {"token": "abc"}) == "/items/42abc"
    with pytest.raises(KeyError):
        template.render({}, {"token": "abc"})
    with pytest.raises(KeyError):
        template.render({"item_id": "42"}, {})


def test_capture_segment_can_carry_taint_in_contract() -> None:
    assert Taint.SECRET == "secret"
