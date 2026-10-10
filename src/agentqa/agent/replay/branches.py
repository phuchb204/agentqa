from __future__ import annotations

from typing import Protocol

from agentqa.agent.replay.contexts import RuntimeContext
from agentqa.contracts.case import (
    AndCondition,
    CaptureCondition,
    ComparisonCondition,
    Condition,
    NotCondition,
    OrCondition,
)


class ConditionProbePort(Protocol):
    async def probe_condition(self, condition: ComparisonCondition) -> bool | None: ...


async def evaluate_condition(condition: Condition, ctx: RuntimeContext, hooks: ConditionProbePort) -> bool:
    if isinstance(condition, AndCondition):
        for child in condition.conditions:
            if not await evaluate_condition(child, ctx, hooks):
                return False
        return True
    if isinstance(condition, OrCondition):
        for child in condition.conditions:
            if await evaluate_condition(child, ctx, hooks):
                return True
        return False
    if isinstance(condition, NotCondition):
        return not await evaluate_condition(condition.condition, ctx, hooks)
    if isinstance(condition, CaptureCondition):
        value = ctx.captures.get(condition.name)
        return bool(value) if value is not None else False
    if isinstance(condition, ComparisonCondition):
        result = await hooks.probe_condition(condition)
        return bool(result) if result is not None else False
    return False
