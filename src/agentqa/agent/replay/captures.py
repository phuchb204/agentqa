from __future__ import annotations

from typing import Protocol

from agentqa.agent.replay.contexts import RuntimeContext
from agentqa.contracts.case import CaptureNode, ComparisonCondition
from agentqa.contracts.values import ValueType


class CaptureProbePort(Protocol):
    async def capture_probe(self, probe: ComparisonCondition) -> tuple[bool, str | None]: ...


async def run_capture(node: CaptureNode, ctx: RuntimeContext, hooks: CaptureProbePort) -> tuple[bool, str]:
    satisfied, observed = await hooks.capture_probe(node.probe)
    if node.output.type == ValueType.BOOLEAN:
        value: object = bool(satisfied)
    elif node.output.type == ValueType.INTEGER:
        try:
            value = int(observed) if observed is not None else 0
        except ValueError:
            value = 0
    else:
        value = observed or ""
    ctx.record_capture(node.output.name, value, node.output.taint)
    observed_text = "true" if satisfied else "false"
    if node.output.type != ValueType.BOOLEAN:
        observed_text = str(value)
    return satisfied, observed_text
