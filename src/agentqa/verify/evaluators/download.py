from __future__ import annotations

from agentqa.contracts.verification import AssertionSpec, Comparator
from agentqa.verify.evaluators import Outcome, SceneFacts, capability, from_bool

HANDLED = frozenset({Comparator.DOWNLOAD_MATCHES})


def evaluate(assertion: AssertionSpec, facts: SceneFacts) -> Outcome:
    expectation = assertion.download
    if expectation is None:
        return capability("download_expectation_required")
    entries = facts.downloads()
    matched = []
    for entry in entries:
        if expectation.filename_contains and expectation.filename_contains not in entry.filename:
            continue
        if expectation.media_type and entry.media_type != expectation.media_type:
            continue
        if expectation.sha256 and entry.sha256 != expectation.sha256:
            continue
        matched.append(entry)
    if len(matched) < expectation.minimum_count:
        observed = ";".join(f"{entry.filename}:{entry.media_type}" for entry in entries) or "no_download"
        return from_bool(False, observed=observed)
    last = matched[-1]
    return from_bool(True, observed=f"{last.filename};{last.media_type};{(last.sha256 or '')[:12]}")
