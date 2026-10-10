from __future__ import annotations

from collections.abc import Awaitable, Callable

from agentqa.agent.replay.branches import ConditionProbePort, evaluate_condition
from agentqa.agent.replay.contexts import RuntimeContext
from agentqa.contracts.case import CaseNode, LoopNode


async def run_loop(
    node: LoopNode,
    ctx: RuntimeContext,
    hooks: ConditionProbePort,
    run_node: Callable[[CaseNode], Awaitable[bool]],
) -> bool:
    iterations = 0
    while iterations < node.max_iterations:
        if not await evaluate_condition(node.condition, ctx, hooks):
            break
        iterations += 1
        instance = f"{node.id}#{iterations}"
        ctx.instance_path.append(instance)
        try:
            for child in node.body:
                if not await run_node(child):
                    return False
            ctx.visited_instances.append(instance)
        finally:
            ctx.instance_path.pop()
    return True
