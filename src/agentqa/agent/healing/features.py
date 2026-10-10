from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from agentqa.agent.identity.resolver import SceneCandidate
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.values import LiteralValue

FEATURE_KEYS = ("role", "name", "context", "stable_attribute", "geometry")
SCORING_ATTRIBUTES = ("id", "data-testid", "name", "aria-label", "label")


@dataclass(frozen=True)
class CandidateFeatures:
    scores: dict[str, float]
    missing: frozenset[str]
    reasons: tuple[str, ...]

    def coverage(self, weights: dict[str, float]) -> float:
        total = sum(weights.values())
        if total <= 0:
            return 0.0
        present = sum(weight for key, weight in weights.items() if key not in self.missing)
        return present / total

    def weighted_score(self, weights: dict[str, float]) -> float:
        present = sum(weight for key, weight in weights.items() if key not in self.missing)
        if present <= 0:
            return 0.0
        total = sum(weights[key] * self.scores.get(key, 0.0) for key in self.scores if key not in self.missing)
        return round(total / present, 4)


def name_similarity(expected: str | None, actual: str | None) -> float | None:
    if expected is None:
        return None
    if actual is None:
        return 0.0
    left = expected.strip().casefold()
    right = actual.strip().casefold()
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return 0.7
    return round(SequenceMatcher(None, left, right).ratio(), 4)


def scope_value(descriptor: TargetDescriptor) -> str | None:
    scope = descriptor.entity_scope
    if scope is None or not isinstance(scope.value, LiteralValue):
        return None
    value = scope.value.value
    return value if isinstance(value, str) else None


def candidate_features(
    descriptor: TargetDescriptor,
    candidate: SceneCandidate,
    *,
    frame_key: str | None,
) -> CandidateFeatures:
    scores: dict[str, float] = {}
    missing: set[str] = set()
    reasons: list[str] = []

    if descriptor.role is None:
        missing.add("role")
    else:
        matched = (candidate.role or "").casefold() == descriptor.role.casefold()
        scores["role"] = 1.0 if matched else 0.0
        reasons.append("role_match" if matched else "role_mismatch")

    similarity = name_similarity(descriptor.name, candidate.name)
    if similarity is None:
        missing.add("name")
    else:
        scores["name"] = similarity
        reasons.append(f"name_similarity={similarity}")

    scope = scope_value(descriptor)
    if scope is not None:
        entity_text = candidate.entity_text if candidate.entity_text is not None else candidate.text or ""
        matched = scope in entity_text
        scores["context"] = 1.0 if matched else 0.0
        reasons.append("entity_scope_match" if matched else "entity_scope_mismatch")
    elif frame_key is not None and candidate.frame_key is not None:
        matched = candidate.frame_key == frame_key
        scores["context"] = 1.0 if matched else 0.0
        reasons.append("frame_match" if matched else "frame_mismatch")
    else:
        missing.add("context")

    if not descriptor.attributes:
        missing.add("stable_attribute")
    else:
        comparable = {key: value for key, value in descriptor.attributes.items() if key in SCORING_ATTRIBUTES}
        if not comparable:
            missing.add("stable_attribute")
        else:
            matched = sum(1 for key, value in comparable.items() if candidate.attributes.get(key) == value)
            scores["stable_attribute"] = matched / len(comparable)
            reasons.append(f"stable_attribute={matched}/{len(comparable)}")

    missing.add("geometry")

    return CandidateFeatures(scores=scores, missing=frozenset(missing), reasons=tuple(reasons))


def descriptor_signature(descriptor: TargetDescriptor) -> str:
    parts = [(descriptor.role or "").casefold(), (descriptor.name or "").strip().casefold()]
    return "|".join(parts)
