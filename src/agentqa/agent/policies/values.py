from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.values import CaptureValue, LiteralValue, ParameterValue, SecretValue, ValueExpr


class ValueResolutionError(RuntimeError):
    def __init__(self, reason: str, code: ErrorCode = ErrorCode.INPUT_INVALID) -> None:
        self.reason = reason
        self.code = code
        super().__init__(reason)


@dataclass(frozen=True)
class ResolutionReceipt:
    expr: ValueExpr | None
    source: str
    generated: bool = False


ValueGenerator = Callable[[str], Awaitable[str]]

PRE_RESOLVED_KINDS = ("secret",)


class ValueResolver:
    def __init__(
        self,
        *,
        generator: ValueGenerator | None = None,
        generator_allowed: bool = False,
    ) -> None:
        self._generator = generator
        self._generator_allowed = generator_allowed
        self.generated_calls = 0

    async def resolve(
        self,
        *,
        node_value: ValueExpr | None,
        proposal_value: ValueExpr | None,
        parameters: dict[str, str],
        captures: dict[str, str],
        target_intent: str | None,
    ) -> ResolutionReceipt:
        if node_value is not None:
            self._validate_known(node_value, parameters, captures)
            source = "node_secret" if isinstance(node_value, SecretValue) else "node"
            return ResolutionReceipt(expr=node_value, source=source)
        if isinstance(proposal_value, SecretValue):
            raise ValueResolutionError("Policy không được đưa secret value", ErrorCode.SECRET_INTERPOLATION)
        if isinstance(proposal_value, LiteralValue):
            return ResolutionReceipt(expr=proposal_value, source="proposal")
        if isinstance(proposal_value, ParameterValue):
            if proposal_value.name not in parameters:
                raise ValueResolutionError(f"Thiếu parameter '{proposal_value.name}'", ErrorCode.UNKNOWN_REFERENCE)
            return ResolutionReceipt(expr=proposal_value, source="proposal")
        if isinstance(proposal_value, CaptureValue):
            if proposal_value.name not in captures:
                raise ValueResolutionError(f"Thiếu capture '{proposal_value.name}'", ErrorCode.UNKNOWN_REFERENCE)
            return ResolutionReceipt(expr=proposal_value, source="proposal")
        if self._generator is not None and self._generator_allowed and target_intent:
            generated = await self._generator(target_intent)
            self.generated_calls += 1
            return ResolutionReceipt(
                expr=LiteralValue(kind="literal", value=generated),
                source="generated",
                generated=True,
            )
        raise ValueResolutionError(
            "Không có giá trị fill hợp lệ (literal/parameter/capture/generation)",
            ErrorCode.CAPABILITY_UNAVAILABLE,
        )

    def _validate_known(self, expr: ValueExpr, parameters: dict[str, str], captures: dict[str, str]) -> None:
        if isinstance(expr, ParameterValue) and expr.name not in parameters:
            raise ValueResolutionError(f"Thiếu parameter '{expr.name}'", ErrorCode.UNKNOWN_REFERENCE)
        if isinstance(expr, CaptureValue) and expr.name not in captures:
            raise ValueResolutionError(f"Thiếu capture '{expr.name}'", ErrorCode.UNKNOWN_REFERENCE)
