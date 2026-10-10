from __future__ import annotations

from agentqa.contracts.verification import AssertionSpec, Comparator
from agentqa.verify.evaluators import Outcome, SceneFacts, capability, dynamic_value, from_bool

HANDLED = frozenset(
    {
        Comparator.UNIQUE,
        Comparator.COUNT_EQUALS,
    }
)

ENTITY_KEYS = frozenset({"entity_count_equals"})


def evaluate(assertion: AssertionSpec, facts: SceneFacts) -> Outcome:
    target = assertion.target
    if target is None or target.entity_scope is None:
        return capability("entity_scope_required")
    count = facts.count(target)
    if assertion.comparator == Comparator.UNIQUE:
        return from_bool(count == 1, observed=f"count={count}")
    if assertion.comparator == Comparator.COUNT_EQUALS:
        expected, error = dynamic_value(assertion.expected, facts)
        if error is not None:
            return capability(error)
        if isinstance(expected, bool) or not isinstance(expected, int):
            return capability()
        return from_bool(count == expected, observed=f"count={count}")
    return capability()
