from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from agentqa.contracts.canonical import digest_content
from agentqa.contracts.errors import AgentQAValidationError, ErrorCode, field_error
from agentqa.contracts.values import StrictModel

MANIFEST_SCHEMA = "experiment-manifest/1"

FORBIDDEN_ARM_COMBOS = (("jev_cascade", "vision_first"),)
VALID_MODES = ("agent", "replay")


class Arm(StrictModel):
    arm_id: str
    mode: Literal["agent", "replay"]
    policy: str
    observation: str = "semantic"
    healing: bool = False
    plan_ref: str | None = None
    baseline: bool = False
    cohorts: list[str] = Field(default_factory=lambda: ["default"])


class SampleDesign(StrictModel):
    unit: str = "case_family"
    confidence: float = 0.95
    non_inferiority_margin: float | None = None
    pilot_ref: str | None = None
    repetitions: int = 1


class Randomisation(StrictModel):
    block_seed: int = 20261010
    order: Literal["randomised", "fixed"] = "randomised"


class Budgets(StrictModel):
    max_calls: int
    max_cost_usd: float
    routes: dict[str, str] = Field(default_factory=dict)


class CacheSettings(StrictModel):
    bypass_local: bool = True
    record_provider_cache: bool = True


class AnalysisSettings(StrictModel):
    primary_endpoints: list[str] = Field(default_factory=lambda: ["oracle_task_success"])
    comparisons: list[list[str]] = Field(default_factory=list)
    bootstrap_seed: int = 20261010
    bootstrap_replicates: int = 10_000
    multiple_comparison: Literal["holm"] = "holm"


class ExperimentManifest(StrictModel):
    schema_version: Literal["experiment-manifest/1"] = MANIFEST_SCHEMA
    experiment_id: str
    version: str
    research_question: Literal["rq1", "rq2", "rq3"]
    corpus: dict[str, list[str]]
    arms: list[Arm]
    randomisation: Randomisation = Randomisation()
    samples: SampleDesign = SampleDesign()
    budgets: Budgets
    cache: CacheSettings = CacheSettings()
    analysis: AnalysisSettings = AnalysisSettings()
    profile_refs: dict[str, str] = Field(default_factory=dict)
    price_receipts: list[str] = Field(default_factory=list)
    capability_receipts: list[str] = Field(default_factory=list)
    variant_tokens: dict[str, list[str]] = Field(default_factory=dict)
    seeds: list[int] = Field(default_factory=lambda: [20261010])

    @model_validator(mode="after")
    def validate_arms(self) -> ExperimentManifest:
        if not self.arms:
            raise AgentQAValidationError([field_error(("arms",), ErrorCode.INPUT_INVALID, "arms rỗng")])
        arm_ids = [arm.arm_id for arm in self.arms]
        if len(set(arm_ids)) != len(arm_ids):
            raise AgentQAValidationError([field_error(("arms",), ErrorCode.INPUT_INVALID, "arm_id trùng")])
        for arm in self.arms:
            for policy, observation in FORBIDDEN_ARM_COMBOS:
                if arm.policy == policy and arm.observation == observation:
                    raise AgentQAValidationError(
                        [
                            field_error(
                                ("arms",),
                                ErrorCode.INPUT_INVALID,
                                f"tổ hợp {policy}+{observation} không hợp lệ",
                            )
                        ]
                    )
        if self.budgets.max_calls <= 0 or self.budgets.max_cost_usd <= 0:
            raise AgentQAValidationError([field_error(("budgets",), ErrorCode.INPUT_INVALID, "budget phải dương")])
        return self

    def digest(self) -> str:
        return digest_content(self.model_dump(mode="json"))


class Incompatibility(StrictModel):
    code: str
    detail: str
    blocking: bool = True


def validate_manifest(manifest: ExperimentManifest) -> list[Incompatibility]:
    incompatibilities: list[Incompatibility] = []
    cases = manifest.corpus.get("cases", [])
    if not cases:
        incompatibilities.append(Incompatibility(code="missing_cases", detail="corpus.cases rỗng"))
    for arm in manifest.arms:
        if arm.mode == "replay" and arm.policy in ("llm", "jev_cascade"):
            incompatibilities.append(
                Incompatibility(
                    code="arm_mode_policy_mismatch",
                    detail=f"{arm.arm_id}: replay không dùng policy {arm.policy}",
                )
            )
        if arm.observation == "vision_first":
            capabilities = manifest.capability_receipts
            if not any("image" in receipt for receipt in capabilities):
                incompatibilities.append(
                    Incompatibility(
                        code="image_capability_unverified",
                        detail=f"{arm.arm_id}: vision_first cần capability receipt ảnh",
                        blocking=False,
                    )
                )
    if manifest.research_question == "rq1":
        policies = {arm.policy for arm in manifest.arms}
        observations = {arm.observation for arm in manifest.arms}
        if policies != {"llm"}:
            incompatibilities.append(Incompatibility(code="rq1_policy", detail="RQ1 chỉ dùng policy llm"))
        if not {"hybrid", "vision_first"} <= observations:
            incompatibilities.append(Incompatibility(code="rq1_observations", detail="RQ1 cần hybrid và vision_first"))
    if manifest.research_question == "rq2" and len(manifest.arms) < 4:
        incompatibilities.append(Incompatibility(code="rq2_arms", detail="RQ2 cần bốn arm"))
    if manifest.research_question == "rq3" and len(manifest.arms) < 5:
        incompatibilities.append(Incompatibility(code="rq3_arms", detail="RQ3 cần năm arm"))
    return incompatibilities
