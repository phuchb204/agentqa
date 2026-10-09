from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from agentqa.agent.observation.hybrid import (
    CapabilityBlockedError,
    CapabilityGate,
    HybridPolicy,
    compose_hybrid,
)
from agentqa.agent.observation.provenance import InputAuditor
from agentqa.contracts.capabilities import (
    CapabilityKind,
    CapabilityReceipt,
    CapabilityStatus,
)
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.models import ProviderRoute
from agentqa.contracts.observation import (
    HybridTrigger,
    Modality,
    SemanticCandidate,
    VisionSnapshot,
    VisionViewport,
)

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
ROUTE = ProviderRoute.OPENCODE_GO
MODEL = "deepseek-v4.1-flash"


def receipt(
    *,
    status: CapabilityStatus,
    verified_at: datetime = NOW,
    expires_at: datetime | None = None,
) -> CapabilityReceipt:
    return CapabilityReceipt(
        receipt_id=uuid4(),
        route=ROUTE,
        model_requested=MODEL,
        model_resolved=MODEL,
        adapter_schema_version="opencode-go-chat/1",
        request_digest="req-digest",
        result_digest="res-digest",
        capabilities={CapabilityKind.IMAGE: status},
        route_epoch="epoch-1",
        verified_at=verified_at,
        expires_at=expires_at or (verified_at + timedelta(days=7)),
    )


def candidate(candidate_id: str, role: str, name: str, provenance: str = "dom") -> SemanticCandidate:
    return SemanticCandidate(candidate_id=candidate_id, role=role, name=name, provenance=provenance)


def policy(*receipts: CapabilityReceipt) -> HybridPolicy:
    return HybridPolicy(CapabilityGate(receipts), route=ROUTE, model=MODEL)


def test_semantic_sufficient_needs_no_image() -> None:
    decision = policy(receipt(status=CapabilityStatus.VERIFIED)).decide(
        target=TargetDescriptor(intent="submit"),
        candidates=[candidate("c0", "button", "Gửi")],
        now=NOW,
    )
    assert decision.use_image is False
    assert decision.triggers == []
    assert decision.reason == "semantic_sufficient"


def test_visual_ref_triggers_image_with_verified_receipt() -> None:
    decision = policy(receipt(status=CapabilityStatus.VERIFIED)).decide(
        target=TargetDescriptor(intent="open_chart", visual_ref="chart-canvas"),
        candidates=[candidate("c0", "button", "Xem biểu đồ")],
        now=NOW,
    )
    assert decision.use_image is True
    assert HybridTrigger.VISUAL_REF in decision.triggers
    assert decision.cost_ref is not None
    assert "image_escalation" in decision.cost_ref


def test_visual_candidate_triggers_image() -> None:
    decision = policy(receipt(status=CapabilityStatus.VERIFIED)).decide(
        target=TargetDescriptor(intent="open", name="Sơ đồ"),
        candidates=[candidate("c0", "canvas", "Sơ đồ")],
        now=NOW,
    )
    assert decision.use_image is True
    assert HybridTrigger.VISUAL_TARGET in decision.triggers


def test_same_name_candidates_trigger_ambiguity() -> None:
    decision = policy(receipt(status=CapabilityStatus.VERIFIED)).decide(
        target=TargetDescriptor(intent="click"),
        candidates=[candidate("c0", "button", "Xoá"), candidate("c1", "button", "Xoá")],
        now=NOW,
    )
    assert decision.use_image is True
    assert HybridTrigger.AMBIGUOUS_CANDIDATES in decision.triggers


def test_structured_need_context_triggers_image() -> None:
    decision = policy(receipt(status=CapabilityStatus.VERIFIED)).decide(
        target=None,
        candidates=[candidate("c0", "button", "A")],
        structured_need_context=True,
        now=NOW,
    )
    assert decision.use_image is True
    assert HybridTrigger.STRUCTURED_NEED_CONTEXT in decision.triggers


def test_missing_receipt_blocks_image_step() -> None:
    decision = policy().decide(
        target=TargetDescriptor(intent="open_chart", visual_ref="chart-canvas"),
        candidates=[candidate("c0", "button", "Xem")],
        now=NOW,
    )
    assert decision.use_image is False
    assert decision.blocked_capability == "image_receipt_missing"
    assert decision.reason == "capability_blocked"


def test_expired_receipt_blocks_image_step() -> None:
    old = receipt(
        status=CapabilityStatus.VERIFIED,
        verified_at=NOW - timedelta(days=30),
        expires_at=NOW - timedelta(days=1),
    )
    decision = policy(old).decide(
        target=TargetDescriptor(intent="open_chart", visual_ref="chart-canvas"),
        candidates=[candidate("c0", "button", "Xem")],
        now=NOW,
    )
    assert decision.blocked_capability == "image_receipt_expired"


def test_unsupported_image_capability_blocks() -> None:
    decision = policy(receipt(status=CapabilityStatus.UNSUPPORTED)).decide(
        target=TargetDescriptor(intent="open_chart", visual_ref="chart-canvas"),
        candidates=[candidate("c0", "button", "Xem")],
        now=NOW,
    )
    assert decision.use_image is False
    assert decision.blocked_capability == "image_unsupported"


def test_require_image_raises_with_reason() -> None:
    gate = CapabilityGate()
    with pytest.raises(CapabilityBlockedError) as excinfo:
        gate.require_image(route=ROUTE, model=MODEL, now=NOW)
    assert excinfo.value.reason == "image_receipt_missing"


def test_compose_hybrid_records_modality_and_requires_vision() -> None:
    from agentqa.contracts.observation import BudgetManifest, RedactionStatus, SemanticSnapshot

    semantic = SemanticSnapshot(
        observation_id=uuid4(),
        version=1,
        session_key="s",
        page_key="main",
        scene_version=1,
        budget=BudgetManifest(profile_id="semantic", profile_version="2"),
        redaction=RedactionStatus.REDACTED,
    )
    audit = InputAuditor().audit(
        observation_id=semantic.observation_id,
        modality=Modality.HYBRID,
        payload={"candidates": []},
        image_bytes=b"png",
        scene_version=1,
    )
    decision = policy(receipt(status=CapabilityStatus.VERIFIED)).decide(
        target=TargetDescriptor(intent="open_chart", visual_ref="chart"),
        candidates=[candidate("c0", "button", "Xem")],
        now=NOW,
    )
    vision = VisionSnapshot(
        observation_id=semantic.observation_id,
        version=1,
        session_key="s",
        page_key="main",
        scene_version=1,
        image_ref="vision://x",
        image_digest="d",
        image_bytes=3,
        viewport=VisionViewport(width=100, height=100),
        layout_digest="l",
    )
    envelope = compose_hybrid(
        semantic=semantic,
        vision=vision,
        decision=decision,
        audit=audit,
        payload={"candidates": [], "image": {"ref": "vision://x"}},
    )
    assert envelope.modality is Modality.HYBRID
    assert envelope.triggers == decision.triggers
    with pytest.raises(ValueError):
        compose_hybrid(
            semantic=semantic,
            vision=None,
            decision=decision,
            audit=audit,
            payload={"candidates": []},
        )
