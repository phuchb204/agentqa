from __future__ import annotations

from agentqa.agent.identity.resolver import SceneCandidate
from agentqa.contracts.identity import EntityScope, TargetDescriptor
from agentqa.contracts.values import LiteralValue

SYNTHETIC_TEST_PROFILE_DOC = {
    "profile_id": "healing-synthetic-v1",
    "version": "1",
    "ranker": "heuristic",
    "evidence": "synthetic_test",
    "weights": {"role": 0.2, "name": 0.4, "context": 0.25, "stable_attribute": 0.1, "geometry": 0.05},
    "min_score": 0.55,
    "margin_min": 0.15,
    "min_coverage": 0.5,
    "max_candidates": 24,
}


def synthetic_profile(**overrides):
    from agentqa.contracts.calibration import CalibrationProfile

    document = dict(SYNTHETIC_TEST_PROFILE_DOC)
    document.update(overrides)
    return CalibrationProfile.model_validate(document)


def measured_profile(**overrides):
    document = dict(SYNTHETIC_TEST_PROFILE_DOC)
    document.update(
        {
            "profile_id": "healing-measured-v1",
            "evidence": "measured",
            "receipt_ref": "tests/receipts/calibration-healing.json",
            "bounds": {"false_heal_upper": 0.05, "refusal_lower": 0.9},
        }
    )
    document.update(overrides)
    return document


def scope(value: str) -> EntityScope:
    return EntityScope(field="text", value=LiteralValue(kind="literal", value=value))


def delete_descriptor(item_name: str = "Việc A") -> TargetDescriptor:
    return TargetDescriptor(intent="delete_item", role="button", name="Xoá", entity_scope=scope(item_name))


def delete_scene(item_name: str = "Việc A", *, button_name: str = "Xoá", candidate_id: str = "c0", **kwargs):
    return SceneCandidate(
        candidate_id=candidate_id,
        role="button",
        name=button_name,
        text=button_name,
        entity_text=f"{item_name} Chưa xong",
        attributes=kwargs.pop("attributes", {}),
        **kwargs,
    )
