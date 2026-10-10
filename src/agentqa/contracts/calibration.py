from __future__ import annotations

from enum import StrEnum

from pydantic import model_validator

from agentqa.contracts.errors import AgentQAValidationError, ErrorCode, field_error
from agentqa.contracts.values import StrictModel


class RankerKind(StrEnum):
    HEURISTIC = "heuristic"
    LLM = "llm"
    CASCADE = "cascade"


class CalibrationEvidence(StrEnum):
    SYNTHETIC_TEST = "synthetic_test"
    MEASURED = "measured"


class FeatureWeights(StrictModel):
    role: float = 0.2
    name: float = 0.4
    context: float = 0.25
    stable_attribute: float = 0.1
    geometry: float = 0.05


class CalibrationProfile(StrictModel):
    profile_id: str
    version: str
    ranker: RankerKind = RankerKind.HEURISTIC
    evidence: CalibrationEvidence = CalibrationEvidence.SYNTHETIC_TEST
    receipt_ref: str | None = None
    bounds: dict[str, float] = {}
    weights: FeatureWeights = FeatureWeights()
    min_score: float = 0.55
    margin_min: float = 0.15
    min_coverage: float = 0.5
    max_candidates: int = 24

    @model_validator(mode="after")
    def require_measured_receipt(self) -> CalibrationProfile:
        if self.evidence == CalibrationEvidence.MEASURED and (not self.receipt_ref or not self.bounds):
            raise AgentQAValidationError(
                [
                    field_error(
                        ("receipt_ref",),
                        ErrorCode.INPUT_INVALID,
                        "Profile measured cần calibration receipt và bound",
                    )
                ]
            )
        return self

    def production_ready(self) -> bool:
        return self.evidence == CalibrationEvidence.MEASURED and bool(self.receipt_ref) and bool(self.bounds)


class HealingReadiness(StrictModel):
    verified: bool
    reason: str
    profile_id: str
    version: str

    @classmethod
    def from_profile(cls, profile: CalibrationProfile) -> HealingReadiness:
        if profile.evidence == CalibrationEvidence.SYNTHETIC_TEST:
            reason = "synthetic_profile"
        elif not profile.receipt_ref:
            reason = "missing_receipt"
        elif not profile.bounds:
            reason = "missing_bounds"
        else:
            reason = "calibrated"
        return cls(
            verified=profile.production_ready(),
            reason=reason,
            profile_id=profile.profile_id,
            version=profile.version,
        )
