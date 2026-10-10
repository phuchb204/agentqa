from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit, urlunsplit

from agentqa.contracts.verification import AssertionSpec, Comparator
from agentqa.verify.evaluators import Outcome, SceneFacts, capability, dynamic_value, from_bool

HANDLED = frozenset({Comparator.URL_PATH_EQUALS, Comparator.URL_EQUALS})


def normalize_url(url: str) -> str:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    default = {"http": 80, "https": 443}.get(scheme)
    if port is not None and port == default:
        port = None
    netloc = host if port is None else f"{host}:{port}"
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    query_pairs = sorted(parse_qsl(parts.query, keep_blank_values=True))
    query = "&".join(f"{key}={value}" for key, value in query_pairs)
    return urlunsplit((scheme, netloc, path, query, ""))


def evaluate(assertion: AssertionSpec, facts: SceneFacts) -> Outcome:
    current = facts.url()
    if assertion.comparator == Comparator.URL_PATH_EQUALS:
        expected, error = dynamic_value(assertion.expected, facts)
        if error is not None or not isinstance(expected, str):
            return capability(error)
        path = urlsplit(current).path
        return from_bool(path == expected, observed=path)
    if assertion.comparator == Comparator.URL_EQUALS:
        expected, error = dynamic_value(assertion.expected, facts)
        if error is not None or not isinstance(expected, str):
            return capability(error)
        normalized_expected = normalize_url(expected)
        normalized_current = normalize_url(current)
        return from_bool(normalized_current == normalized_expected, observed=normalized_current)
    return capability()
