from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = "evaluation/1"
EVALUATOR_VERSION = "evaluator/1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskOutcome(StrEnum):
    TRUE = "true"
    FALSE = "false"
    UNSCORABLE = "unscorable"


class DetectionLabel(StrEnum):
    POSITIVE = "detection_positive"
    MISSED = "detection_missed"


class HealingLabel(StrEnum):
    CORRECT = "correct_heal"
    FALSE = "false_heal"
    REFUSED = "refusal"
    UNSCORABLE = "unscorable"


class VariantClassification(StrEnum):
    BENIGN = "benign"
    DISTRACTOR = "distractor"
    BUSINESS_BUG = "business_bug"
    TEMPORAL = "temporal"


class OracleOpportunity(StrictModel):
    opportunity_id: str
    step_id: str
    original_identity: str
    expected_identity: str | None = None
    expected_entity: str | None = None
    kind: str = "mismatch"


class OracleRecord(StrictModel):
    case_key: str
    variant_token: str | None = None
    app: str
    fixture_ref: str
    classification: VariantClassification = VariantClassification.BENIGN
    expected_effects: list[dict[str, Any]] = []
    opportunities: list[OracleOpportunity] = []


class HealingAttempt(StrictModel):
    opportunity_id: str
    attempt_ref: str
    decision: str
    actual_identity: str | None = None
    guard_checks: list[str] = []
    postconditions_ok: bool | None = None
    dispatch_outcome: str | None = None
    error: str | None = None


class EvaluationInput(StrictModel):
    run_id: str
    execution_status: str
    product_verdict: str | None = None
    product_gate: str | None = None
    snapshot_digest: str = ""
    scheduled: bool = True
    namespace: str = ""
    parameters: dict[str, Any] = {}
    probe: dict[str, Any] | None = None
    probe_missing: bool = False
    actual_target_entity: str | None = None
    healing_attempts: list[HealingAttempt] = []
    assertion_statuses: dict[str, str] = {}


class OpportunityLabel(StrictModel):
    opportunity_id: str
    detection: DetectionLabel
    healing: list[HealingLabel] = []
    actual_identities: list[str | None] = []


class EvaluationResult(StrictModel):
    schema_version: str = SCHEMA_VERSION
    evaluator_version: str = EVALUATOR_VERSION
    input_digest: str
    oracle_digest: str
    task_outcome: TaskOutcome
    scorable: bool
    unscorable_reason: str | None = None
    product_verdict: str | None = None
    product_gate: str | None = None
    false_pass: bool = False
    labels: list[OpportunityLabel] = []
    counters: dict[str, Any] = {}
    success_lower_bound: float | None = None
    success_upper_bound: float | None = None
    coverage: float | None = None
