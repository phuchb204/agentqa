from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from agentqa.contracts.capabilities import CapabilityKind, CapabilityReceipt, CapabilityStatus
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.models import ProviderRoute
from agentqa.contracts.observation import (
    HybridDecision,
    HybridTrigger,
    Modality,
    ModalityAudit,
    ObservationEnvelope,
    SemanticCandidate,
    SemanticSnapshot,
    VisionSnapshot,
)

VISUAL_ROLES = frozenset({"img", "canvas", "svg"})


class CapabilityBlockedError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class CapabilityGate:
    def __init__(self, receipts: Iterable[CapabilityReceipt] = ()) -> None:
        self._receipts = list(receipts)

    def add(self, receipt: CapabilityReceipt) -> None:
        self._receipts.append(receipt)

    def latest(self, *, route: ProviderRoute, model: str) -> CapabilityReceipt | None:
        matching = [
            receipt for receipt in self._receipts if receipt.route is route and receipt.model_requested == model
        ]
        if not matching:
            return None
        return max(matching, key=lambda receipt: receipt.verified_at)

    def image_status(self, *, route: ProviderRoute, model: str, now: datetime | None = None) -> CapabilityStatus:
        moment = now or datetime.now(UTC)
        receipt = self.latest(route=route, model=model)
        if receipt is None:
            return CapabilityStatus.UNVERIFIED
        if not receipt.is_valid_at(moment):
            return CapabilityStatus.BLOCKED
        return receipt.capability_status(CapabilityKind.IMAGE)

    def require_image(self, *, route: ProviderRoute, model: str, now: datetime | None = None) -> CapabilityReceipt:
        moment = now or datetime.now(UTC)
        receipt = self.latest(route=route, model=model)
        if receipt is None:
            raise CapabilityBlockedError("image_receipt_missing")
        if not receipt.is_valid_at(moment):
            raise CapabilityBlockedError("image_receipt_expired")
        status = receipt.capability_status(CapabilityKind.IMAGE)
        if status is not CapabilityStatus.VERIFIED:
            raise CapabilityBlockedError(f"image_{status.value}")
        return receipt


class HybridPolicy:
    def __init__(self, gate: CapabilityGate, *, route: ProviderRoute, model: str) -> None:
        self._gate = gate
        self._route = route
        self._model = model

    def decide(
        self,
        *,
        target: TargetDescriptor | None,
        candidates: list[SemanticCandidate],
        structured_need_context: bool = False,
        now: datetime | None = None,
    ) -> HybridDecision:
        triggers = self._triggers(target, candidates, structured_need_context)
        if not triggers:
            return HybridDecision(use_image=False, triggers=[], reason="semantic_sufficient")
        try:
            self._gate.require_image(route=self._route, model=self._model, now=now)
        except CapabilityBlockedError as error:
            return HybridDecision(
                use_image=False,
                triggers=triggers,
                reason="capability_blocked",
                blocked_capability=error.reason,
            )
        return HybridDecision(
            use_image=True,
            triggers=triggers,
            reason="image_required",
            cost_ref=f"image_escalation:{'+'.join(trigger.value for trigger in triggers)}",
        )

    def _triggers(
        self,
        target: TargetDescriptor | None,
        candidates: list[SemanticCandidate],
        structured_need_context: bool,
    ) -> list[HybridTrigger]:
        triggers: list[HybridTrigger] = []
        if structured_need_context:
            triggers.append(HybridTrigger.STRUCTURED_NEED_CONTEXT)
        if target is not None and target.visual_ref:
            triggers.append(HybridTrigger.VISUAL_REF)
        if target is not None and _matches_visual_candidate(target, candidates):
            triggers.append(HybridTrigger.VISUAL_TARGET)
        if _ambiguous(candidates):
            triggers.append(HybridTrigger.AMBIGUOUS_CANDIDATES)
        deduplicated: list[HybridTrigger] = []
        for trigger in triggers:
            if trigger not in deduplicated:
                deduplicated.append(trigger)
        return deduplicated


def compose_hybrid(
    *,
    semantic: SemanticSnapshot,
    vision: VisionSnapshot | None,
    decision: HybridDecision,
    audit: ModalityAudit,
    payload: dict,
) -> ObservationEnvelope:
    if decision.use_image and vision is None:
        raise ValueError("Hybrid dùng ảnh nhưng thiếu vision snapshot")
    modality = Modality.HYBRID if decision.use_image else Modality.SEMANTIC
    return ObservationEnvelope(
        semantic=semantic,
        vision=vision,
        modality=modality,
        triggers=list(decision.triggers),
        audit=audit,
        payload=payload,
    )


def _matches_visual_candidate(target: TargetDescriptor, candidates: list[SemanticCandidate]) -> bool:
    for candidate in candidates:
        if candidate.role not in VISUAL_ROLES:
            continue
        if target.name and candidate.name == target.name:
            return True
        if target.role and candidate.role == target.role and not target.name:
            return True
    return False


def _ambiguous(candidates: list[SemanticCandidate]) -> bool:
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        if candidate.provenance == "engine":
            continue
        key = (candidate.role, candidate.name)
        if not candidate.name:
            continue
        if key in seen:
            return True
        seen.add(key)
    return False


__all__ = [
    "CapabilityBlockedError",
    "CapabilityGate",
    "HybridPolicy",
    "compose_hybrid",
]
