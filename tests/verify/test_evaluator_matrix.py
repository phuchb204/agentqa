from __future__ import annotations

import io

from PIL import Image

from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.values import CaptureValue
from agentqa.contracts.verification import (
    AssertionStatus,
    Comparator,
    DownloadExpectation,
    MaskBox,
    NetworkFilter,
    VisualExpectation,
)
from agentqa.verify.evaluators import DownloadEntry, NetworkEntry, evaluate_assertion
from agentqa.verify.evaluators.url import normalize_url
from tests.verify.conftest import FakeFacts, assertion, entity_scope, target


def png_bytes(colour: tuple[int, int, int], size: tuple[int, int] = (4, 4)) -> bytes:
    image = Image.new("RGB", size, colour)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_absence_vs_unavailable_are_distinct() -> None:
    absent = assertion(
        "absent",
        Comparator.ABSENT,
        target_descriptor=target("row", role="listitem"),
        expected=True,
    )
    facts = FakeFacts(counts={"row": 0})
    outcome = evaluate_assertion(absent, facts)
    assert outcome.status == AssertionStatus.PASSED

    unavailable = assertion("missing", Comparator.ABSENT, expected=True)
    outcome = evaluate_assertion(unavailable, FakeFacts())
    assert outcome.status == AssertionStatus.ERROR


def test_negative_and_hidden_comparators() -> None:
    not_equals = assertion(
        "not_equals",
        Comparator.NOT_EQUALS,
        target_descriptor=target("status"),
        expected="Đã xong",
    )
    assert evaluate_assertion(not_equals, FakeFacts(texts={"status": "Chưa xong"})).status == AssertionStatus.PASSED
    assert evaluate_assertion(not_equals, FakeFacts(texts={"status": "Đã xong"})).status == AssertionStatus.FAILED

    hidden = assertion("hidden", Comparator.HIDDEN, target_descriptor=target("panel"), expected=True)
    assert evaluate_assertion(hidden, FakeFacts(counts={"panel": 1}, visibles={"panel": False})).status == (
        AssertionStatus.PASSED
    )
    assert evaluate_assertion(hidden, FakeFacts(counts={"panel": 1}, visibles={"panel": True})).status == (
        AssertionStatus.FAILED
    )


def test_text_regex_value_and_state_comparators() -> None:
    matches = assertion(
        "regex",
        Comparator.TEXT_MATCHES,
        target_descriptor=target("code"),
        expected=r"^Mã: \d{4}$",
    )
    assert evaluate_assertion(matches, FakeFacts(texts={"code": "Mã: 1234"})).status == AssertionStatus.PASSED
    assert evaluate_assertion(matches, FakeFacts(texts={"code": "Mã: 12"})).status == AssertionStatus.FAILED

    value = assertion(
        "value",
        Comparator.VALUE_EQUALS,
        target_descriptor=target("input"),
        expected="xin chào",
    )
    assert evaluate_assertion(value, FakeFacts(values={"input": "xin chào"})).status == AssertionStatus.PASSED
    assert evaluate_assertion(value, FakeFacts(values={"input": "khác"})).status == AssertionStatus.FAILED

    checked = assertion("checked", Comparator.STATE_CHECKED, target_descriptor=target("toggle"), expected=True)
    assert evaluate_assertion(checked, FakeFacts(checkeds={"toggle": True})).status == AssertionStatus.PASSED
    assert evaluate_assertion(checked, FakeFacts(checkeds={"toggle": False})).status == AssertionStatus.FAILED

    enabled = assertion("enabled", Comparator.STATE_ENABLED, target_descriptor=target("submit"), expected=False)
    assert evaluate_assertion(enabled, FakeFacts(enableds={"submit": False})).status == AssertionStatus.PASSED


def test_entity_relations_use_scope_and_dynamic_expected() -> None:
    unique = assertion(
        "unique_row",
        Comparator.UNIQUE,
        target_descriptor=TargetDescriptor(intent="row", role="listitem", entity_scope=entity_scope("Việc A")),
    )
    facts = FakeFacts(counts={"row": 1})
    assert evaluate_assertion(unique, facts).status == AssertionStatus.PASSED

    ambiguous = FakeFacts(counts={"row": 2})
    assert evaluate_assertion(unique, ambiguous).status == AssertionStatus.FAILED

    dynamic = assertion(
        "captured_count",
        Comparator.COUNT_EQUALS,
        target_descriptor=TargetDescriptor(intent="row", role="listitem", entity_scope=entity_scope("Việc A")),
        expected_expr=CaptureValue(kind="capture", name="rows"),
    )
    facts = FakeFacts(counts={"row": 2}, captures={"rows": 2})
    assert evaluate_assertion(dynamic, facts).status == AssertionStatus.PASSED
    missing_capture = FakeFacts(counts={"row": 2})
    assert evaluate_assertion(dynamic, missing_capture).status == AssertionStatus.ERROR


def test_url_normalization_matrix() -> None:
    assert normalize_url("HTTPS://Example.COM:443/tasks/") == "https://example.com/tasks"
    assert normalize_url("http://example.com:8080/a?b=2&a=1") == "http://example.com:8080/a?a=1&b=2"

    path = assertion("path", Comparator.URL_PATH_EQUALS, expected="/tasks")
    assert evaluate_assertion(path, FakeFacts(url="http://x.example/tasks?page=2")).status == AssertionStatus.PASSED

    equals = assertion("url", Comparator.URL_EQUALS, expected="https://example.com/tasks/")
    assert evaluate_assertion(equals, FakeFacts(url="https://EXAMPLE.com:443/tasks")).status == AssertionStatus.PASSED
    assert evaluate_assertion(equals, FakeFacts(url="https://example.com/other")).status == AssertionStatus.FAILED


def test_network_scope_filter_and_missing_evidence() -> None:
    entries = [
        NetworkEntry(
            method="POST", url="http://x.example/api/tasks", status=201, body_digest="a" * 64, body_excerpt='{"id": 1}'
        ),
        NetworkEntry(
            method="GET", url="http://x.example/api/tasks", status=200, body_digest="b" * 64, body_excerpt="[]"
        ),
    ]
    spec = assertion(
        "network",
        Comparator.NETWORK_REQUEST,
        expected=True,
    )
    spec = spec.model_copy(update={"network": NetworkFilter(method="POST", path_contains="/api/tasks", status=201)})
    outcome = evaluate_assertion(spec, FakeFacts(network=entries))
    assert outcome.status == AssertionStatus.PASSED

    wrong_status = spec.model_copy(
        update={"network": NetworkFilter(method="POST", path_contains="/api/tasks", status=500)}
    )
    outcome = evaluate_assertion(wrong_status, FakeFacts(network=entries))
    assert outcome.status == AssertionStatus.FAILED

    body_filter = spec.model_copy(update={"network": NetworkFilter(path_contains="/api", body_contains='"id"')})
    assert evaluate_assertion(body_filter, FakeFacts(network=entries)).status == AssertionStatus.PASSED

    no_filter = spec.model_copy(update={"network": None})
    assert evaluate_assertion(no_filter, FakeFacts(network=entries)).status == AssertionStatus.ERROR


def test_download_evidence_metadata_and_hash() -> None:
    entry = DownloadEntry(filename="bao-cao.txt", media_type="text/plain", size_bytes=12, sha256="c" * 64)
    spec = assertion("download", Comparator.DOWNLOAD_MATCHES, expected=True)
    spec = spec.model_copy(update={"download": DownloadExpectation(filename_contains="bao-cao")})
    assert evaluate_assertion(spec, FakeFacts(downloads=[entry])).status == AssertionStatus.PASSED

    wrong_hash = spec.model_copy(update={"download": DownloadExpectation(sha256="d" * 64)})
    assert evaluate_assertion(wrong_hash, FakeFacts(downloads=[entry])).status == AssertionStatus.FAILED

    missing = spec.model_copy(update={"download": DownloadExpectation(media_type="application/pdf")})
    assert evaluate_assertion(missing, FakeFacts(downloads=[entry])).status == AssertionStatus.FAILED


def test_ambiguous_row_with_scope_is_failed_not_guessed() -> None:
    unique = assertion(
        "ambiguous_row",
        Comparator.UNIQUE,
        target_descriptor=TargetDescriptor(intent="row", role="listitem", entity_scope=entity_scope("Việc trùng")),
    )
    facts = FakeFacts(counts={"row": 3})
    outcome = evaluate_assertion(unique, facts)
    assert outcome.status == AssertionStatus.FAILED
    assert outcome.observed == "count=3"


def test_changed_layout_context_baseline_incompatible() -> None:
    baseline = png_bytes((10, 20, 30), size=(4, 4))
    observed = png_bytes((10, 20, 30), size=(5, 4))
    spec = assertion("visual", Comparator.VISUAL_MATCH, expected=True)
    spec = spec.model_copy(update={"visual": VisualExpectation(baseline_ref="base-layout", max_diff_ratio=0.0)})
    facts = FakeFacts(baselines={"base-layout": baseline}, screenshot=observed)
    outcome = evaluate_assertion(spec, facts)
    assert outcome.status == AssertionStatus.ERROR
    assert outcome.reason == "baseline_incompatible"


def test_visual_masked_evidence_missing_and_wrong_baseline() -> None:
    baseline = png_bytes((255, 0, 0))
    identical = png_bytes((255, 0, 0))
    changed = Image.new("RGB", (4, 4), (255, 0, 0))
    changed.putpixel((0, 0), (0, 0, 255))
    buffer = io.BytesIO()
    changed.save(buffer, format="PNG")
    changed_bytes = buffer.getvalue()

    strict = VisualExpectation(baseline_ref="base-1", max_diff_ratio=0.0)
    spec = assertion("visual", Comparator.VISUAL_MATCH, expected=True)
    spec = spec.model_copy(update={"visual": strict})

    pass_facts = FakeFacts(baselines={"base-1": baseline}, screenshot=identical)
    assert evaluate_assertion(spec, pass_facts).status == AssertionStatus.PASSED

    fail_facts = FakeFacts(baselines={"base-1": baseline}, screenshot=changed_bytes)
    outcome = evaluate_assertion(spec, fail_facts)
    assert outcome.status == AssertionStatus.FAILED
    assert "diff_ratio=0.0625" in (outcome.observed or "")

    masked = strict.model_copy(update={"masks": [MaskBox(x=0, y=0, width=1, height=1)]})
    masked_spec = spec.model_copy(update={"visual": masked})
    assert evaluate_assertion(masked_spec, fail_facts).status == AssertionStatus.PASSED

    wrong_baseline = FakeFacts(baselines={"base-1": png_bytes((255, 0, 0), size=(8, 8))}, screenshot=identical)
    outcome = evaluate_assertion(spec, wrong_baseline)
    assert outcome.status == AssertionStatus.ERROR
    assert outcome.reason == "baseline_incompatible"

    missing_baseline = FakeFacts(baselines={}, screenshot=identical)
    assert evaluate_assertion(spec, missing_baseline).status == AssertionStatus.ERROR

    unsupported = spec.model_copy(
        update={"visual": VisualExpectation(baseline_ref="base-1", profile_version="visual/9", max_diff_ratio=0.0)}
    )
    outcome = evaluate_assertion(unsupported, pass_facts)
    assert outcome.status == AssertionStatus.ERROR
    assert outcome.reason == "visual_profile_unsupported"

    full_mask = strict.model_copy(update={"masks": [MaskBox(x=0, y=0, width=4, height=4)]})
    full_mask_spec = spec.model_copy(update={"visual": full_mask})
    outcome = evaluate_assertion(full_mask_spec, fail_facts)
    assert outcome.status == AssertionStatus.ERROR
    assert outcome.reason == "mask_covers_all"
