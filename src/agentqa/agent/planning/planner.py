from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256

from agentqa.contracts.case import CaseContent
from agentqa.contracts.values import LiteralValue

PLANNER_VERSION = "planner/1"


@dataclass(frozen=True)
class Subgoal:
    subgoal_id: str
    goal: str
    node_ids: tuple[str, ...]
    requirement_refs: tuple[str, ...] = ()
    order: int = 0
    value_hint: str | None = None


@dataclass(frozen=True)
class PlanningPlan:
    plan_id: str
    version: str
    goal: str
    subgoals: tuple[Subgoal, ...] = field(default_factory=tuple)
    required_nodes: tuple[str, ...] = ()
    required_assertions: tuple[str, ...] = ()


def build_plan(case: CaseContent) -> PlanningPlan:
    subgoals: list[Subgoal] = []
    order = 0
    for node in case.nodes:
        kind = getattr(node, "kind", "")
        if kind == "action":
            operation = getattr(node, "operation", None)
            target = getattr(node, "target", None)
            intent = getattr(target, "intent", None)
            goal = f"{operation.value if operation else 'action'} {intent or ''}".strip()
            value_hint = None
            node_value = getattr(node, "value", None)
            if isinstance(node_value, LiteralValue) and isinstance(node_value.value, str):
                value_hint = node_value.value
            subgoals.append(
                Subgoal(
                    subgoal_id=f"node:{node.id}",
                    goal=goal,
                    node_ids=(node.id,),
                    requirement_refs=tuple(case.requirements),
                    order=order,
                    value_hint=value_hint,
                )
            )
            order += 1
        elif kind == "checkpoint":
            subgoals.append(
                Subgoal(
                    subgoal_id=f"checkpoint:{node.id}",
                    goal=f"xác nhận checkpoint {node.id}",
                    node_ids=(node.id,),
                    requirement_refs=tuple(case.requirements),
                    order=order,
                )
            )
            order += 1
    plan_digest = sha256(f"{PLANNER_VERSION}|{case.logical_key}".encode()).hexdigest()[:16]
    return PlanningPlan(
        plan_id=f"plan:{plan_digest}",
        version=PLANNER_VERSION,
        goal=case.goal,
        subgoals=tuple(subgoals),
        required_nodes=tuple(case.completion.required_nodes),
        required_assertions=tuple(case.completion.required_assertions),
    )
