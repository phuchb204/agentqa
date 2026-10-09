from __future__ import annotations

import inspect
import typing
from typing import Any

from agentqa.contracts import ports

FORBIDDEN_MODULE_PREFIXES = ("playwright", "sqlalchemy", "fastapi", "starlette")

EXPECTED_PORTS: dict[str, set[str]] = {
    "ClockPort": {"utc_now", "monotonic"},
    "BrowserReadPort": {"observe", "probe", "read_download_metadata", "capture_safe_evidence"},
    "BrowserActionPort": {"dispatch", "query_outcome"},
    "IdentityPort": {"resolve", "rank"},
    "VerificationPort": {"evaluate_checkpoint", "finalize", "evaluate_gate"},
    "GenerativeModelPort": {"generate"},
    "DecisionModelPort": {"decide"},
    "EventSink": {"append"},
    "CallLedgerPort": {"record"},
    "ArtifactPort": {"put_bytes", "scoped_ref", "mark_integrity"},
    "SecretGrantPort": {"issue", "resolve"},
    "FixturePort": {"prepare", "reset", "cleanup"},
    "BudgetPort": {"reserve", "settle", "remaining"},
}


def protocol_classes() -> list[type]:
    return [obj for obj in vars(ports).values() if inspect.isclass(obj) and getattr(obj, "_is_protocol", False)]


def iter_annotation_types(annotation: Any) -> typing.Iterator[Any]:
    if annotation is None or annotation is type(None):
        return
    origin = typing.get_origin(annotation)
    if origin is not None:
        for argument in typing.get_args(annotation):
            yield from iter_annotation_types(argument)
        return
    yield annotation


def test_protocols_do_not_leak_foreign_framework_types() -> None:
    checked = 0
    for protocol in protocol_classes():
        for name, member in inspect.getmembers(protocol, inspect.isfunction):
            hints = typing.get_type_hints(member)
            for hint in hints.values():
                for resolved in iter_annotation_types(hint):
                    module = getattr(resolved, "__module__", "")
                    assert not module.startswith(FORBIDDEN_MODULE_PREFIXES), (
                        f"{protocol.__name__}.{name} leaks {resolved!r} from {module}"
                    )
                    checked += 1
    assert checked > 0


def test_expected_ports_expose_expected_methods() -> None:
    for name, methods in EXPECTED_PORTS.items():
        protocol = getattr(ports, name)
        assert getattr(protocol, "_is_protocol", False), f"{name} must be a Protocol"
        for method in methods:
            assert hasattr(protocol, method), f"{name} missing method {method}"


def test_no_module_in_ports_imports_forbidden_frameworks() -> None:
    source = inspect.getsource(ports)
    for forbidden in FORBIDDEN_MODULE_PREFIXES:
        assert f"import {forbidden}" not in source
        assert f"from {forbidden}" not in source
