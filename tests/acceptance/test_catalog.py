from __future__ import annotations

from dataclasses import replace

from tools.acceptance.catalog import (
    EXPECTED_AC,
    EXPECTED_NFR,
    ArtifactCheck,
    Scenario,
    build_catalog,
    validate_catalog,
)


def test_catalog_is_complete_and_valid() -> None:
    catalog = build_catalog()
    assert validate_catalog(catalog) == []
    assert tuple(scenario.id for scenario in catalog.scenarios) == (*EXPECTED_AC, *EXPECTED_NFR)


def test_catalog_scenarios_have_observable_fields() -> None:
    catalog = build_catalog()
    for scenario in catalog.scenarios:
        assert scenario.business_effect.strip()
        assert scenario.proof.strip()
        assert scenario.denominator.strip()
        assert scenario.check_ids
        assert scenario.requirement_refs


def test_validate_detects_missing_required_scenario() -> None:
    catalog = build_catalog()
    trimmed = replace(catalog, scenarios=tuple(s for s in catalog.scenarios if s.id != "AC-24"))
    gaps = validate_catalog(trimmed)
    assert any("AC-24" in gap for gap in gaps)


def test_validate_detects_unknown_scenario() -> None:
    catalog = build_catalog()
    extra = Scenario("AC-99", "x", "x", "x", "x", ("pytest.ac01.replay",), ("FR-01",))
    modified = replace(catalog, scenarios=(*catalog.scenarios, extra))
    gaps = validate_catalog(modified)
    assert any("AC-99" in gap for gap in gaps)


def test_validate_detects_unknown_check_reference() -> None:
    catalog = build_catalog()
    broken = replace(
        catalog.scenarios[0],
        check_ids=("pytest.khong_ton_tai",),
    )
    modified = replace(catalog, scenarios=(broken, *catalog.scenarios[1:]))
    gaps = validate_catalog(modified)
    assert any("pytest.khong_ton_tai" in gap for gap in gaps)


def test_validate_detects_duplicate_check_id() -> None:
    catalog = build_catalog()
    duplicate = ArtifactCheck("pytest.ac01.replay", "tool", "artifacts/x.json")
    modified = replace(catalog, checks=(*catalog.checks, duplicate))
    gaps = validate_catalog(modified)
    assert any("trùng" in gap for gap in gaps)


def test_validate_detects_unused_check() -> None:
    catalog = build_catalog()
    orphan = ArtifactCheck("artifact.mo_coi", "tool", "artifacts/x.json")
    modified = replace(catalog, checks=(*catalog.checks, orphan))
    gaps = validate_catalog(modified)
    assert any("artifact.mo_coi" in gap for gap in gaps)


def test_validate_detects_empty_fields() -> None:
    catalog = build_catalog()
    broken = replace(catalog.scenarios[0], proof=" ")
    modified = replace(catalog, scenarios=(broken, *catalog.scenarios[1:]))
    gaps = validate_catalog(modified)
    assert any("proof" in gap for gap in gaps)


def test_validate_detects_missing_requirement_refs() -> None:
    catalog = build_catalog()
    broken = replace(catalog.scenarios[0], requirement_refs=())
    modified = replace(catalog, scenarios=(broken, *catalog.scenarios[1:]))
    gaps = validate_catalog(modified)
    assert any("requirement_refs" in gap for gap in gaps)


def test_validate_detects_duplicate_scenario_id() -> None:
    catalog = build_catalog()
    duplicated = replace(catalog, scenarios=(*catalog.scenarios, catalog.scenarios[0]))
    gaps = validate_catalog(duplicated)
    assert any("scenario id trùng" in gap for gap in gaps)
