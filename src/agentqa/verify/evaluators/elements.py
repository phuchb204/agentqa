from __future__ import annotations

import re

from agentqa.contracts.verification import AssertionSpec, Comparator
from agentqa.verify.evaluators import (
    Outcome,
    SceneFacts,
    capability,
    dynamic_value,
    from_bool,
    literal_value,
)

HANDLED = frozenset(
    {
        Comparator.EXISTS,
        Comparator.ABSENT,
        Comparator.UNIQUE,
        Comparator.VISIBLE,
        Comparator.HIDDEN,
        Comparator.COUNT_EQUALS,
        Comparator.COUNT_GREATER_OR_EQUAL,
        Comparator.EQUALS,
        Comparator.TEXT_EQUALS,
        Comparator.CONTAINS,
        Comparator.NOT_EQUALS,
        Comparator.TEXT_MATCHES,
        Comparator.VALUE_EQUALS,
        Comparator.STATE_CHECKED,
        Comparator.STATE_ENABLED,
        Comparator.ATTRIBUTE_EQUALS,
    }
)

TARGET_REQUIRED = frozenset(HANDLED)


def evaluate(assertion: AssertionSpec, facts: SceneFacts) -> Outcome:
    target = assertion.target
    comparator = assertion.comparator
    if target is None:
        return capability()
    if comparator == Comparator.EXISTS:
        count = facts.count(target)
        wanted = bool(literal_value(assertion.expected)) if assertion.expected is not None else True
        return from_bool((count > 0) == wanted, observed=str(count))
    if comparator == Comparator.ABSENT:
        count = facts.count(target)
        wanted = bool(literal_value(assertion.expected)) if assertion.expected is not None else True
        return from_bool((count == 0) == wanted, observed=str(count))
    if comparator == Comparator.UNIQUE:
        count = facts.count(target)
        return from_bool(count == 1, observed=str(count))
    if comparator == Comparator.VISIBLE:
        visible = facts.visible(target)
        wanted = bool(literal_value(assertion.expected)) if assertion.expected is not None else True
        return from_bool(visible == wanted, observed=str(visible))
    if comparator == Comparator.HIDDEN:
        hidden = facts.hidden(target)
        wanted = bool(literal_value(assertion.expected)) if assertion.expected is not None else True
        return from_bool(hidden == wanted, observed=str(hidden))
    if comparator in (Comparator.COUNT_EQUALS, Comparator.COUNT_GREATER_OR_EQUAL):
        expected, error = dynamic_value(assertion.expected, facts)
        if error is not None:
            return capability(error)
        if not isinstance(expected, int) or isinstance(expected, bool):
            return capability()
        count = facts.count(target)
        if comparator == Comparator.COUNT_EQUALS:
            return from_bool(count == expected, observed=str(count))
        return from_bool(count >= expected, observed=str(count))
    if comparator == Comparator.ATTRIBUTE_EQUALS:
        if not target.attributes:
            return capability()
        name = next(iter(target.attributes))
        actual = facts.attribute(target, name)
        expected, error = dynamic_value(assertion.expected, facts)
        if error is not None:
            return capability(error)
        wanted = expected if expected is not None else target.attributes[name]
        return from_bool(actual == wanted, observed=actual or "")
    if comparator == Comparator.STATE_CHECKED:
        checked = facts.checked(target)
        if checked is None:
            return capability()
        wanted = bool(literal_value(assertion.expected)) if assertion.expected is not None else True
        return from_bool(checked == wanted, observed=str(checked))
    if comparator == Comparator.STATE_ENABLED:
        enabled = facts.enabled(target)
        if enabled is None:
            return capability()
        wanted = bool(literal_value(assertion.expected)) if assertion.expected is not None else True
        return from_bool(enabled == wanted, observed=str(enabled))
    if comparator == Comparator.VALUE_EQUALS:
        actual_value = facts.value(target)
        expected, error = dynamic_value(assertion.expected, facts)
        if error is not None:
            return capability(error)
        if actual_value is None:
            return from_bool(False, observed="absent")
        return from_bool(actual_value == str(expected), observed=actual_value)
    if comparator == Comparator.TEXT_MATCHES:
        expected, error = dynamic_value(assertion.expected, facts)
        if error is not None or not isinstance(expected, str):
            return capability(error)
        text = facts.text(target)
        if text is None:
            return from_bool(False, observed="absent")
        normalized = text.strip()
        try:
            matched = re.search(expected, normalized) is not None
        except re.error:
            return capability("invalid_regex")
        return from_bool(matched, observed=normalized)
    if comparator in (Comparator.EQUALS, Comparator.TEXT_EQUALS, Comparator.CONTAINS, Comparator.NOT_EQUALS):
        text = facts.text(target)
        if comparator == Comparator.NOT_EQUALS:
            expected, error = dynamic_value(assertion.expected, facts)
            if error is not None:
                return capability(error)
            if text is None:
                return Outcome(status=_passed(), observed="absent")
            return from_bool(text.strip() != str(expected or ""), observed=text)
        if text is None:
            return from_bool(False, observed="absent")
        expected, error = dynamic_value(assertion.expected, facts)
        if error is not None or not isinstance(expected, str):
            return capability(error)
        normalized = text.strip()
        if comparator == Comparator.CONTAINS:
            return from_bool(expected in normalized, observed=normalized)
        return from_bool(normalized == expected, observed=normalized)
    return capability()


def _passed():
    from agentqa.contracts.verification import AssertionStatus

    return AssertionStatus.PASSED
