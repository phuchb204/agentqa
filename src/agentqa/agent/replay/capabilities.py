from __future__ import annotations

from dataclasses import dataclass, field

from agentqa.contracts.actions import Operation
from agentqa.contracts.case import (
    ActionNode,
    BranchNode,
    CaptureNode,
    CaseContent,
    CaseNode,
    CheckpointNode,
    LoopNode,
)

SUPPORTED_OPERATIONS = frozenset(Operation)


def supported_operations() -> tuple[str, ...]:
    return tuple(sorted(operation.value for operation in SUPPORTED_OPERATIONS))


@dataclass(frozen=True)
class CapabilityReport:
    supported: bool
    unsupported_nodes: tuple[str, ...] = ()
    unsupported_operations: tuple[str, ...] = ()
    reasons: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, object]:
        return {
            "supported": self.supported,
            "unsupported_nodes": list(self.unsupported_nodes),
            "unsupported_operations": list(self.unsupported_operations),
            "reasons": list(self.reasons),
        }


def validate_case(case: CaseContent) -> CapabilityReport:
    unsupported_nodes: list[str] = []
    unsupported_operations: list[str] = []
    reasons: list[str] = []
    _validate_nodes(case.nodes, unsupported_nodes, unsupported_operations, reasons)
    return CapabilityReport(
        supported=not unsupported_nodes and not unsupported_operations,
        unsupported_nodes=tuple(unsupported_nodes),
        unsupported_operations=tuple(unsupported_operations),
        reasons=tuple(reasons),
    )


def _validate_nodes(
    nodes: list[CaseNode],
    unsupported_nodes: list[str],
    unsupported_operations: list[str],
    reasons: list[str],
) -> None:
    for node in nodes:
        if isinstance(node, ActionNode):
            if node.operation not in SUPPORTED_OPERATIONS:
                unsupported_operations.append(node.operation.value)
                reasons.append(f"operation_not_supported:{node.operation.value}")
        elif isinstance(node, (CheckpointNode, CaptureNode)):
            continue
        elif isinstance(node, BranchNode):
            _validate_nodes(node.then_nodes, unsupported_nodes, unsupported_operations, reasons)
            _validate_nodes(node.else_nodes, unsupported_nodes, unsupported_operations, reasons)
        elif isinstance(node, LoopNode):
            if node.max_iterations < 1:
                unsupported_nodes.append(node.id)
                reasons.append(f"loop_unbounded:{node.id}")
                continue
            _validate_nodes(node.body, unsupported_nodes, unsupported_operations, reasons)
        else:
            unsupported_nodes.append(node.id)
            reasons.append(f"node_kind_not_supported:{node.kind}")
