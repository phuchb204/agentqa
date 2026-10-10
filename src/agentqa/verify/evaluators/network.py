from __future__ import annotations

from agentqa.contracts.verification import AssertionSpec, Comparator
from agentqa.verify.evaluators import Outcome, SceneFacts, capability, from_bool

HANDLED = frozenset({Comparator.NETWORK_REQUEST})


def evaluate(assertion: AssertionSpec, facts: SceneFacts) -> Outcome:
    if assertion.network is None:
        return capability("network_filter_required")
    entries = facts.network(assertion.network)
    count = len(entries)
    minimum = assertion.network.minimum_count
    if count < minimum:
        return from_bool(False, observed=f"matched={count}")
    digest = entries[-1].body_digest or ""
    return from_bool(True, observed=f"matched={count};last={entries[-1].status};digest={digest[:12]}")
