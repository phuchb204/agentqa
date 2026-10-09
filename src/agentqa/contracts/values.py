from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from agentqa.contracts.errors import AgentQAValidationError, ErrorCode, field_error

MAX_SAFE_INTEGER = 2**53 - 1

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Taint(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SECRET = "secret"


class ValueType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"


def ensure_safe_json(value: object, path: tuple[str | int, ...] = ()) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise AgentQAValidationError(
                [field_error(path, ErrorCode.UNSAFE_JSON, f"Số nguyên vượt giới hạn an toàn: {value!r}")]
            )
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise AgentQAValidationError([field_error(path, ErrorCode.UNSAFE_JSON, "NaN/Infinity không được phép")])
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AgentQAValidationError([field_error(path, ErrorCode.UNSAFE_JSON, "Khóa JSON phải là chuỗi")])
            ensure_safe_json(item, (*path, key))
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            ensure_safe_json(item, (*path, index))
        return
    raise AgentQAValidationError(
        [field_error(path, ErrorCode.UNSAFE_JSON, f"Kiểu không hỗ trợ trong JSON: {type(value).__name__}")]
    )


class Money(StrictModel):
    amount: Decimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("amount", mode="before")
    @classmethod
    def reject_float(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("money amount must be a decimal string or Decimal, not float")
        return value

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return format(value, "f")


class LiteralValue(StrictModel):
    kind: Literal["literal"]
    value: JsonValue

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: object) -> object:
        ensure_safe_json(value)
        return value


class ParameterValue(StrictModel):
    kind: Literal["parameter"]
    name: str
    type: ValueType = ValueType.STRING


class CaptureValue(StrictModel):
    kind: Literal["capture"]
    name: str
    type: ValueType = ValueType.STRING
    taint: Taint = Taint.INTERNAL


class SecretValue(StrictModel):
    kind: Literal["secret"]
    credential_ref: str


ValueExpr = Annotated[
    LiteralValue | ParameterValue | CaptureValue | SecretValue,
    Field(discriminator="kind"),
]


class LiteralSegment(StrictModel):
    kind: Literal["literal"]
    text: str


class ParameterSegment(StrictModel):
    kind: Literal["parameter"]
    name: str


class CaptureSegment(StrictModel):
    kind: Literal["capture"]
    name: str


TemplateSegment = Annotated[
    LiteralSegment | ParameterSegment | CaptureSegment,
    Field(discriminator="kind"),
]


class StringTemplate(StrictModel):
    segments: list[TemplateSegment]

    def render(self, parameters: Mapping[str, str], captures: Mapping[str, str]) -> str:
        rendered: list[str] = []
        for segment in self.segments:
            if isinstance(segment, LiteralSegment):
                rendered.append(segment.text)
            elif isinstance(segment, ParameterSegment):
                if segment.name not in parameters:
                    raise KeyError(segment.name)
                rendered.append(parameters[segment.name])
            else:
                if segment.name not in captures:
                    raise KeyError(segment.name)
                rendered.append(captures[segment.name])
        return "".join(rendered)


class SensitiveValue:
    __slots__ = ("_secret",)

    def __init__(self, secret: str) -> None:
        object.__setattr__(self, "_secret", secret)

    def reveal(self) -> str:
        return self._secret

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("SensitiveValue is immutable")

    def __repr__(self) -> str:
        return "SensitiveValue(***)"

    def __str__(self) -> str:
        return "SensitiveValue(***)"

    def __reduce__(self) -> Any:
        raise TypeError("SensitiveValue cannot be serialized")

    def __getstate__(self) -> Any:
        raise TypeError("SensitiveValue cannot be serialized")
