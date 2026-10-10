from __future__ import annotations

from dataclasses import dataclass, field

from agentqa.contracts.values import CaptureValue, LiteralValue, ParameterValue, Taint, ValueExpr


@dataclass
class RuntimeContext:
    captures: dict[str, object] = field(default_factory=dict)
    capture_taint: dict[str, Taint] = field(default_factory=dict)
    parameters: dict[str, object] = field(default_factory=dict)
    branch_decisions: dict[str, str] = field(default_factory=dict)
    instance_path: list[str] = field(default_factory=list)
    visited_instances: list[str] = field(default_factory=list)

    def record_capture(self, name: str, value: object, taint: Taint) -> None:
        self.captures[name] = value
        self.capture_taint[name] = taint

    def current_instance(self, node_id: str) -> str:
        suffix = "/".join(self.instance_path)
        return f"{node_id}@{suffix}" if suffix else node_id

    def resolve_value(self, value: ValueExpr | None) -> ValueExpr | None:
        if isinstance(value, CaptureValue):
            captured = self.captures.get(value.name)
            if captured is None:
                return None
            return LiteralValue(kind="literal", value=captured)
        if isinstance(value, ParameterValue):
            parameter = self.parameters.get(value.name)
            if parameter is None:
                return None
            return LiteralValue(kind="literal", value=parameter)
        return value
