from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agentqa.contracts.runs import GateResult, Verdict

STRICT = "strict"
ALLOW_HEALING = "allow_healing"
PROFILES = (STRICT, ALLOW_HEALING)


@dataclass(frozen=True)
class GateContext:
    completed: bool
    revision_ready: bool
    evidence_ok: bool
    healed: bool = False
    healing_guards_ok: bool = False
    degraded: bool = False
    provisional: bool = False


@dataclass(frozen=True)
class GateDecision:
    result: GateResult
    reasons: tuple[str, ...] = ()
    accepted: bool = False
    business_failure: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "result": self.result.value,
            "accepted": self.accepted,
            "business_failure": self.business_failure,
            "reasons": list(self.reasons),
        }


def evaluate_gate(profile: str, verdict: Verdict | None, context: GateContext) -> GateDecision:
    if profile not in PROFILES:
        raise ValueError(f"gate profile không hợp lệ: {profile}")
    if verdict is None:
        return GateDecision(result=GateResult.ERROR, reasons=("verdict_active",))
    if verdict == Verdict.FAILED:
        return GateDecision(result=GateResult.REFUSED, reasons=("verdict_failed",), business_failure=True)
    if verdict == Verdict.INCONCLUSIVE:
        return GateDecision(result=GateResult.REFUSED, reasons=("verdict_inconclusive",))
    reasons: list[str] = []
    if not context.completed:
        reasons.append("execution_incomplete")
    if not context.revision_ready:
        reasons.append("revision_not_ready")
    if not context.evidence_ok:
        reasons.append("evidence_missing")
    if context.degraded:
        reasons.append("degraded_not_allowed")
    if context.provisional:
        reasons.append("provisional_not_allowed")
    if context.healed:
        if profile == STRICT:
            reasons.append("healed_not_allowed_in_strict")
        elif not context.healing_guards_ok:
            reasons.append("healing_guards_missing")
    if reasons:
        return GateDecision(result=GateResult.REFUSED, reasons=tuple(reasons))
    return GateDecision(result=GateResult.PASSED, accepted=True)


def exit_code(
    *,
    invalid_pre_submit: bool = False,
    cancelled: bool = False,
    business_failed: bool = False,
    gate_decisions: Sequence[GateDecision] = (),
) -> int:
    if invalid_pre_submit:
        return 64
    if cancelled:
        return 130
    if business_failed:
        return 1
    if any(not decision.accepted for decision in gate_decisions):
        return 2
    return 0
