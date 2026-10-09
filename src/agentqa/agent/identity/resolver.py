from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from agentqa.contracts.identity import EntityScope, LocatorAlternative, TargetDescriptor
from agentqa.contracts.values import LiteralValue

NAME_EXACT_SCORE = 1.0
NAME_CASEFOLD_SCORE = 0.9
NAME_CONTAINS_SCORE = 0.5
ATTRIBUTE_SCORE = 0.2
VISIBLE_SCORE = 0.1
STABLE_ATTRIBUTES = ("id", "data-testid", "name")


@dataclass(frozen=True)
class SceneCandidate:
    candidate_id: str
    role: str | None = None
    name: str | None = None
    text: str | None = None
    frame_key: str | None = None
    visible: bool = True
    enabled: bool = True
    checked: bool | None = None
    attributes: Mapping[str, str] = field(default_factory=dict)
    entity_text: str | None = None

    def stable_signature(self) -> str:
        parts = [self.role or "", (self.name or "").strip().casefold()]
        for key in STABLE_ATTRIBUTES:
            if key in self.attributes:
                parts.append(f"{key}={self.attributes[key]}")
        return "|".join(parts)


@dataclass(frozen=True)
class CandidateMatch:
    candidate: SceneCandidate
    score: float
    reasons: tuple[str, ...] = ()

    @property
    def identity_signature(self) -> str:
        return self.candidate.stable_signature()


class IdentityResolver:
    def __init__(self, *, allow_soft_only: bool = False) -> None:
        self._allow_soft_only = allow_soft_only

    def resolve(
        self,
        descriptor: TargetDescriptor,
        candidates: list[SceneCandidate],
        *,
        frame_key: str | None = None,
    ) -> list[CandidateMatch]:
        matches: list[CandidateMatch] = []
        for candidate in candidates:
            hard = self._hard_match(descriptor, candidate, frame_key=frame_key)
            if hard is None:
                continue
            score, reasons = self._soft_score(descriptor, candidate)
            matches.append(CandidateMatch(candidate=candidate, score=score, reasons=(*hard, *reasons)))
        matches.sort(key=lambda match: (-match.score, match.candidate.candidate_id))
        return matches

    def _hard_match(
        self,
        descriptor: TargetDescriptor,
        candidate: SceneCandidate,
        *,
        frame_key: str | None,
    ) -> tuple[str, ...] | None:
        reasons: list[str] = []
        if frame_key is not None and candidate.frame_key is not None and candidate.frame_key != frame_key:
            return None
        if descriptor.role and (candidate.role or "").casefold() != descriptor.role.casefold():
            return None
        if descriptor.locators:
            if not any(self._locator_matches(alternative, candidate) for alternative in descriptor.locators):
                return None
            reasons.append("locator")
        if descriptor.name and not descriptor.locators and not self._name_matches(descriptor.name, candidate):
            return None
        for key, value in descriptor.attributes.items():
            if candidate.attributes.get(key) != value:
                return None
        scope = self._scope_value(descriptor.entity_scope)
        if scope is not None:
            entity_text = candidate.entity_text if candidate.entity_text is not None else candidate.text or ""
            if scope not in entity_text:
                return None
            reasons.append("entity_scope")
        if not reasons:
            reasons.append("structural")
        return tuple(reasons)

    def _soft_score(self, descriptor: TargetDescriptor, candidate: SceneCandidate) -> tuple[float, tuple[str, ...]]:
        score = 0.0
        reasons: list[str] = []
        if descriptor.name and candidate.name:
            if candidate.name == descriptor.name:
                score += NAME_EXACT_SCORE
                reasons.append("name_exact")
            elif candidate.name.casefold() == descriptor.name.casefold():
                score += NAME_CASEFOLD_SCORE
                reasons.append("name_casefold")
            elif descriptor.name.casefold() in candidate.name.casefold():
                score += NAME_CONTAINS_SCORE
                reasons.append("name_contains")
        if any(key == "id" or key == "name" or key.startswith("data-") for key in candidate.attributes):
            score += ATTRIBUTE_SCORE
            reasons.append("stable_attribute")
        if candidate.visible:
            score += VISIBLE_SCORE
            reasons.append("visible")
        return round(min(score, 2.0), 4), tuple(reasons)

    def _locator_matches(self, alternative: LocatorAlternative, candidate: SceneCandidate) -> bool:
        kind = alternative.kind.value
        value = alternative.value
        if kind == "role":
            return (candidate.role or "").casefold() == value.casefold()
        if kind == "label":
            return candidate.attributes.get("label") == value or candidate.name == value
        if kind == "text":
            return value in (candidate.text or "") or candidate.name == value
        if kind == "test_id":
            test_id = candidate.attributes.get("data-testid", "")
            return test_id == value
        if kind == "css":
            if value.startswith("#"):
                return candidate.attributes.get("id") == value[1:]
            return any(candidate.attributes.get(key) is not None for key in STABLE_ATTRIBUTES)
        return False

    def _name_matches(self, expected: str, candidate: SceneCandidate) -> bool:
        for value in (candidate.name, candidate.text):
            if value and (value == expected or value.casefold() == expected.casefold()):
                return True
        return False

    def _scope_value(self, scope: EntityScope | None) -> str | None:
        if scope is None or not isinstance(scope.value, LiteralValue):
            return None
        value = scope.value.value
        return value if isinstance(value, str) else None
