from __future__ import annotations

from collections.abc import Callable
from typing import Any

RefResolver = Callable[[str, str, str], str | None]


def _counter(probe: dict[str, Any], name: str) -> int | None:
    counters = probe.get("counters")
    if not isinstance(counters, dict):
        return None
    value = counters.get(name)
    return int(value) if isinstance(value, int) else 0


def evaluate_effect(
    effect: dict[str, Any],
    *,
    app: str,
    namespace: str,
    probe: dict[str, Any],
    parameters: dict[str, Any],
    ref_resolver: RefResolver | None = None,
) -> bool | None:
    kind = str(effect.get("kind", ""))
    if kind in ("counter_equals", "counter_at_least"):
        value = _counter(probe, str(effect.get("counter", "")))
        if value is None:
            return None
        expected = int(effect.get("value", 0))
        return value == expected if kind == "counter_equals" else value >= expected
    if kind == "label_count_equals":
        label_counts = probe.get("label_counts")
        if not isinstance(label_counts, dict):
            return None
        parameter_name = str(effect.get("parameter", ""))
        label = str(parameters.get(parameter_name, ""))
        if not label:
            return None
        return int(label_counts.get(label, 0)) == int(effect.get("value", 0))
    if kind == "order_count_equals":
        value = probe.get("order_count")
        if value is None:
            return None
        return int(value) == int(effect.get("value", 0))
    if kind == "cart_line_count_equals":
        value = probe.get("cart_line_count")
        if value is None:
            return None
        return int(value) == int(effect.get("value", 0))
    if kind == "field_equals":
        field = str(effect.get("field", ""))
        if field not in probe:
            return None
        return probe.get(field) == effect.get("value")
    if kind == "resolved_target_equals":
        ref_field = str(effect.get("ref_field", ""))
        ref = probe.get(ref_field)
        if not isinstance(ref, str) or ref_resolver is None:
            return None
        resolved = ref_resolver(app, namespace, ref)
        if resolved is None:
            return None
        return resolved == str(effect.get("expected_entity", ""))
    return None


def evaluate_effects(
    effects: list[dict[str, Any]],
    *,
    app: str,
    namespace: str,
    probe: dict[str, Any] | None,
    parameters: dict[str, Any],
    ref_resolver: RefResolver | None = None,
) -> tuple[bool | None, str | None]:
    if probe is None:
        return None, "missing_probe"
    unevaluated = False
    for effect in effects:
        outcome = evaluate_effect(
            effect,
            app=app,
            namespace=namespace,
            probe=probe,
            parameters=parameters,
            ref_resolver=ref_resolver,
        )
        if outcome is None:
            unevaluated = True
            continue
        if not outcome:
            return False, None
    if unevaluated:
        return None, "missing_effect_evidence"
    return True, None
