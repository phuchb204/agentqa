from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from agentqa.contracts.canonical import digest_content
from agentqa.contracts.errors import AgentQAValidationError, ErrorCode, field_error
from agentqa.contracts.values import StrictModel

MANIFEST_SCHEMA = "calibration-manifest/1"
RECEIPT_SCHEMA = "calibration-receipt/1"
CRITERIA_VERSION = "acceptance-refusal-loss/1"


class QualityPolicy(StrictModel):
    max_false_heal_rate: float = 0.01
    confidence: float = 0.95
    scope: str = "healing"
    ordering: list[str] = Field(
        default_factory=lambda: ["false_heal_rate", "refusal_efficiency", "correct_heal_efficiency"]
    )

    @model_validator(mode="after")
    def validate_policy(self) -> QualityPolicy:
        if not 0.0 < self.max_false_heal_rate < 1.0:
            raise AgentQAValidationError(
                [field_error(("quality_policy", "max_false_heal_rate"), ErrorCode.INPUT_INVALID, "ngoài (0, 1)")]
            )
        if not 0.0 < self.confidence < 1.0:
            raise AgentQAValidationError(
                [field_error(("quality_policy", "confidence"), ErrorCode.INPUT_INVALID, "ngoài (0, 1)")]
            )
        return self


class SearchSpace(StrictModel):
    rankers: list[str] = Field(default_factory=lambda: ["heuristic", "llm", "cascade"])
    min_score: list[float] = Field(default_factory=lambda: [0.5, 0.55, 0.6])
    margin_min: list[float] = Field(default_factory=lambda: [0.1, 0.15])
    max_candidates: list[int] = Field(default_factory=lambda: [24])


class Budgets(StrictModel):
    max_calls: int
    max_cost_usd: float
    routes: dict[str, str]
    model_pair: str = "opencode"

    @model_validator(mode="after")
    def validate_pair(self) -> Budgets:
        from agentqa.models.routes import MODEL_PAIRS

        if self.model_pair not in MODEL_PAIRS:
            raise AgentQAValidationError(
                [
                    field_error(
                        ("budgets", "model_pair"), ErrorCode.INPUT_INVALID, f"pair không hỗ trợ: {self.model_pair}"
                    )
                ]
            )
        return self


class CalibrationManifest(StrictModel):
    schema_version: Literal["calibration-manifest/1"] = MANIFEST_SCHEMA
    profile_id: str
    version: str
    feature_schema: str
    question_set: str
    splits: dict[str, list[str]]
    search_space: SearchSpace = SearchSpace()
    quality_policy: QualityPolicy = QualityPolicy()
    budgets: Budgets
    seeds: list[int] = Field(default_factory=lambda: [20261010])

    @model_validator(mode="after")
    def validate_splits(self) -> CalibrationManifest:
        calibration = set(self.splits.get("calibration", []))
        pilot = set(self.splits.get("pilot", []))
        evaluation = set(self.splits.get("evaluation", []))
        if not calibration:
            raise AgentQAValidationError(
                [field_error(("splits", "calibration"), ErrorCode.INPUT_INVALID, "calibration split rỗng")]
            )
        if not evaluation:
            raise AgentQAValidationError(
                [field_error(("splits", "evaluation"), ErrorCode.INPUT_INVALID, "evaluation split rỗng")]
            )
        if calibration & evaluation or calibration & pilot or pilot & evaluation:
            raise AgentQAValidationError(
                [field_error(("splits",), ErrorCode.INPUT_INVALID, "split phải rời nhau theo family")]
            )
        if self.budgets.max_calls <= 0 or self.budgets.max_cost_usd <= 0:
            raise AgentQAValidationError([field_error(("budgets",), ErrorCode.INPUT_INVALID, "budget phải dương")])
        if not self.budgets.routes:
            raise AgentQAValidationError(
                [field_error(("budgets", "routes"), ErrorCode.INPUT_INVALID, "routes pin rỗng")]
            )
        return self

    def digest(self) -> str:
        return digest_content(self.model_dump(mode="json"))


class CandidateResult(StrictModel):
    candidate_id: str
    ranker: str
    params: dict[str, float | int | str] = Field(default_factory=dict)


class TrialLabels(StrictModel):
    false_heal: bool = False
    correct_heal: bool = False
    refusal: bool = False
    unscorable: bool = False
    synthetic: bool = False


class CalibrationTrial(StrictModel):
    candidate_id: str
    case_key: str
    family: str
    split: str
    labels: TrialLabels


class CalibrationReceipt(StrictModel):
    schema_version: Literal["calibration-receipt/1"] = RECEIPT_SCHEMA
    profile_id: str
    version: str
    evidence: Literal["measured", "synthetic_test"]
    sample_units: int
    unscorable_units: int = 0
    groups: int
    bound_upper: float | None
    bound_method: str
    confidence: float
    refusal_coverage: float | None
    criteria_version: str = CRITERIA_VERSION
    profile_digest: str
    manifest_digest: str
    generated_at: datetime
    status: Literal["ready", "provisional"]
    reason: str | None = None
    ranking: list[dict] = Field(default_factory=list)
    sample_size: dict | None = None

    def as_dict(self) -> dict:
        return self.model_dump(mode="json")
