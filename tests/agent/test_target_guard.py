from __future__ import annotations

from agentqa.agent.identity import GuardContext, IdentityResolver, SceneCandidate, TargetGuard
from agentqa.contracts.actions import Operation
from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.identity import EntityScope, LocatorAlternative, LocatorKind, TargetDescriptor
from agentqa.contracts.values import LiteralValue


def scope(value: str) -> EntityScope:
    return EntityScope(field="text", value=LiteralValue(kind="literal", value=value))


def button(name: str, candidate_id: str = "c0", **kwargs) -> SceneCandidate:
    return SceneCandidate(candidate_id=candidate_id, role="button", name=name, text=name, **kwargs)


def test_guard_allows_single_identity_with_proof() -> None:
    guard = TargetGuard()
    descriptor = TargetDescriptor(intent="create", role="button", name="Thêm việc")
    decision = guard.check(
        descriptor,
        [button("Thêm việc"), button("Xoá", candidate_id="c1")],
        GuardContext(operation=Operation.CLICK, current_scene_version=3, expected_scene_version=3),
    )
    assert decision.allowed is True
    assert decision.proof is not None
    assert decision.proof.candidate_id == "c0"
    assert decision.proof.scene_version == 3
    assert "role=button" not in decision.proof.identity_signature


def test_guard_rejects_same_name_duplicates_without_entity_scope() -> None:
    guard = TargetGuard()
    descriptor = TargetDescriptor(intent="delete", role="button", name="Xoá")
    scene = [
        SceneCandidate(candidate_id="c0", role="button", name="Xoá", text="Xoá", entity_text="Việc A"),
        SceneCandidate(candidate_id="c1", role="button", name="Xoá", text="Xoá", entity_text="Việc B"),
    ]
    decision = guard.check(descriptor, scene, GuardContext(operation=Operation.CLICK))
    assert decision.allowed is False
    assert decision.code == ErrorCode.LOCATOR_AMBIGUOUS
    assert decision.matched is None


def test_guard_rejects_reused_dom_id_even_when_selector_resolves() -> None:
    guard = TargetGuard()
    descriptor = TargetDescriptor(
        intent="delete",
        locators=[LocatorAlternative(kind=LocatorKind.CSS, value="#row")],
    )
    scene = [
        SceneCandidate(candidate_id="c0", role="button", name="Xoá", attributes={"id": "row"}),
        SceneCandidate(candidate_id="c1", role="button", name="Xoá", attributes={"id": "row"}),
    ]
    decision = guard.check(descriptor, scene, GuardContext(operation=Operation.CLICK))
    assert decision.allowed is False
    assert decision.code == ErrorCode.LOCATOR_AMBIGUOUS


def test_entity_scope_narrows_to_correct_row() -> None:
    guard = TargetGuard()
    descriptor = TargetDescriptor(intent="delete", role="button", name="Xoá", entity_scope=scope("Việc B"))
    scene = [
        SceneCandidate(candidate_id="c0", role="button", name="Xoá", entity_text="Việc A"),
        SceneCandidate(candidate_id="c1", role="button", name="Xoá", entity_text="Việc B"),
    ]
    decision = guard.check(descriptor, scene, GuardContext(operation=Operation.CLICK))
    assert decision.allowed is True
    assert decision.matched is not None
    assert decision.matched.candidate_id == "c1"


def test_scene_version_expired_rejects_even_if_selector_still_resolves() -> None:
    guard = TargetGuard()
    descriptor = TargetDescriptor(intent="create", role="button", name="Thêm việc")
    decision = guard.check(
        descriptor,
        [button("Thêm việc")],
        GuardContext(operation=Operation.CLICK, expected_scene_version=1, current_scene_version=2),
    )
    assert decision.allowed is False
    assert decision.reason == "scene_proof_expired"


def test_state_requirements_depend_on_operation() -> None:
    guard = TargetGuard()
    descriptor = TargetDescriptor(intent="submit", role="button", name="Gửi")
    disabled = SceneCandidate(candidate_id="c0", role="button", name="Gửi", enabled=False)
    click = guard.check(descriptor, [disabled], GuardContext(operation=Operation.CLICK))
    assert click.allowed is False
    assert click.reason == "state_not_enabled"
    navigate = guard.check(descriptor, [disabled], GuardContext(operation=Operation.NAVIGATE))
    assert navigate.allowed is True


def test_missing_candidate_is_rejected_without_force_click() -> None:
    guard = TargetGuard()
    descriptor = TargetDescriptor(intent="create", role="button", name="Không tồn tại")
    decision = guard.check(descriptor, [button("Thêm việc")], GuardContext(operation=Operation.CLICK))
    assert decision.allowed is False
    assert decision.code == ErrorCode.LOCATOR_MISSING
    assert decision.matched is None


def test_alternative_locators_must_resolve_same_identity() -> None:
    guard = TargetGuard()
    same_identity = TargetDescriptor(
        intent="add",
        locators=[
            LocatorAlternative(kind=LocatorKind.ROLE, value="button"),
            LocatorAlternative(kind=LocatorKind.TEST_ID, value="add-btn"),
        ],
    )
    single = SceneCandidate(candidate_id="c0", role="button", name="Thêm việc", attributes={"data-testid": "add-btn"})
    allowed = guard.check(same_identity, [single], GuardContext(operation=Operation.CLICK))
    assert allowed.allowed is True

    cross_identity = TargetDescriptor(
        intent="add",
        locators=[
            LocatorAlternative(kind=LocatorKind.ROLE, value="button"),
            LocatorAlternative(kind=LocatorKind.TEST_ID, value="secondary"),
        ],
    )
    scene = [
        SceneCandidate(candidate_id="c0", role="button", name="Thêm việc"),
        SceneCandidate(candidate_id="c1", role="button", name="Phụ", attributes={"data-testid": "secondary"}),
    ]
    rejected = guard.check(cross_identity, scene, GuardContext(operation=Operation.CLICK))
    assert rejected.allowed is False
    assert rejected.code == ErrorCode.LOCATOR_AMBIGUOUS


def test_resolver_ranks_soft_signals_without_deciding_identity() -> None:
    resolver = IdentityResolver()
    descriptor = TargetDescriptor(intent="row", role="listitem", entity_scope=scope("Việc A"))
    scene = [
        SceneCandidate(
            candidate_id="c1",
            role="listitem",
            name="Việc A",
            entity_text="Việc A",
            attributes={"data-item-id": "item-1"},
        ),
        SceneCandidate(candidate_id="c0", role="listitem", name="Việc A", entity_text="Việc A"),
    ]
    matches = resolver.resolve(descriptor, scene)
    assert [match.candidate.candidate_id for match in matches] == ["c1", "c0"]
    assert matches[0].score >= matches[1].score
    assert {"entity_scope", "visible"} <= set(matches[0].reasons)
