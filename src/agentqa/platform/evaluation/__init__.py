from __future__ import annotations

from agentqa.platform.evaluation.effects import evaluate_effect, evaluate_effects
from agentqa.platform.evaluation.models import (
    EVALUATOR_VERSION,
    SCHEMA_VERSION,
    DetectionLabel,
    EvaluationInput,
    EvaluationResult,
    HealingAttempt,
    HealingLabel,
    OpportunityLabel,
    OracleOpportunity,
    OracleRecord,
    TaskOutcome,
    VariantClassification,
)
from agentqa.platform.evaluation.scoring import score, success_bounds, target_identity
from agentqa.platform.evaluation.service import EvaluationService

__all__ = [
    "EVALUATOR_VERSION",
    "SCHEMA_VERSION",
    "DetectionLabel",
    "EvaluationInput",
    "EvaluationResult",
    "EvaluationService",
    "HealingAttempt",
    "HealingLabel",
    "OpportunityLabel",
    "OracleOpportunity",
    "OracleRecord",
    "TaskOutcome",
    "VariantClassification",
    "evaluate_effect",
    "evaluate_effects",
    "score",
    "success_bounds",
    "target_identity",
]
