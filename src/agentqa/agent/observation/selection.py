from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from agentqa.contracts.observation import (
    BudgetManifest,
    BudgetProfile,
    SemanticCandidate,
    SemanticRegion,
    SemanticSnapshot,
)

DEFAULT_SEMANTIC_PROFILE = BudgetProfile(
    profile_id="semantic",
    version="2",
    max_candidates=60,
    max_bytes=32_000,
    max_tokens=8_000,
    max_image_bytes=1_500_000,
)

NONE_CONTEXT_TEXT = "none/need_more_context"


def candidate_bytes(candidate: SemanticCandidate) -> int:
    return len(candidate.model_dump_json().encode("utf-8"))


@dataclass
class SelectionResult:
    kept: list[SemanticCandidate]
    regions: list[SemanticRegion] = field(default_factory=list)
    manifest: BudgetManifest = field(default_factory=lambda: BudgetManifest(profile_id="semantic", profile_version="2"))


class BudgetSelector:
    def __init__(self, profile: BudgetProfile | None = None) -> None:
        self.profile = profile or DEFAULT_SEMANTIC_PROFILE

    def select(
        self,
        candidates: list[SemanticCandidate],
        *,
        subgoal_terms: tuple[str, ...] = (),
        mandatory_ids: frozenset[str] = frozenset(),
    ) -> SelectionResult:
        terms = tuple(term.lower() for term in subgoal_terms if term)
        ranked: list[tuple[int, int, SemanticCandidate]] = []
        for index, candidate in enumerate(candidates):
            priority = self._priority(candidate, index, terms, mandatory_ids)
            ranked.append((-priority, index, candidate))
        ranked.sort()
        kept: list[SemanticCandidate] = []
        dropped: list[str] = []
        kept_bytes = 0
        dropped_bytes = 0
        for _priority, _index, candidate in ranked:
            size = candidate_bytes(candidate)
            if len(kept) < self.profile.max_candidates and kept_bytes + size <= self.profile.max_bytes:
                kept.append(candidate)
                kept_bytes += size
            else:
                dropped.append(candidate.candidate_id)
                dropped_bytes += size
        kept.sort(key=lambda item: int(item.candidate_id[1:]))
        truncated = bool(dropped)
        sentinel = None
        if truncated:
            sentinel = SemanticCandidate(
                candidate_id=f"c{len(kept)}",
                role="option",
                name=NONE_CONTEXT_TEXT,
                text=NONE_CONTEXT_TEXT,
                provenance="engine",
            )
            kept.append(sentinel)
        manifest = BudgetManifest(
            profile_id=self.profile.profile_id,
            profile_version=self.profile.version,
            retained=[candidate.candidate_id for candidate in kept],
            dropped=dropped,
            kept_bytes=kept_bytes,
            dropped_bytes=dropped_bytes,
            estimated_tokens=kept_bytes // 4,
            truncated=truncated,
            none_context_sentinel=truncated,
            reason="budget:candidates" if truncated else None,
        )
        return SelectionResult(kept=kept, regions=build_regions(kept), manifest=manifest)

    def expand(
        self,
        snapshot: SemanticSnapshot,
        extra_candidates: list[SemanticCandidate],
        *,
        subgoal_terms: tuple[str, ...] = (),
    ) -> SemanticSnapshot:
        merged = [candidate for candidate in snapshot.candidates if candidate.provenance != "engine"]
        merged.extend(extra_candidates)
        mandatory = frozenset(candidate.candidate_id for candidate in extra_candidates)
        result = self.select(merged, subgoal_terms=subgoal_terms, mandatory_ids=mandatory)
        manifest = result.manifest.model_copy(update={"reason": "expanded:region"})
        return snapshot.model_copy(update={"candidates": result.kept, "regions": result.regions, "budget": manifest})

    def _priority(
        self,
        candidate: SemanticCandidate,
        index: int,
        terms: tuple[str, ...],
        mandatory_ids: frozenset[str],
    ) -> int:
        if candidate.candidate_id in mandatory_ids or candidate.entity_key in mandatory_ids:
            return 1000 - index
        haystack = f"{candidate.role} {candidate.name} {candidate.text}".lower()
        relevance = sum(1 for term in terms if term in haystack)
        visibility = 10 if candidate.visible and candidate.actionability.value == "actionable" else 0
        return relevance * 20 + visibility - index


def build_regions(candidates: list[SemanticCandidate]) -> list[SemanticRegion]:
    grouped: dict[str, list[str]] = {}
    for candidate in candidates:
        if candidate.region:
            grouped.setdefault(candidate.region, []).append(candidate.candidate_id)
    return [
        SemanticRegion(region_id=region_id, kind="entity", candidate_ids=ids)
        for region_id, ids in sorted(grouped.items())
    ]


def provisional_snapshot(
    *,
    observation_id: UUID,
    version: int,
    session_key: str,
    page_key: str,
    scene_version: int,
) -> SemanticSnapshot:
    from agentqa.contracts.observation import RedactionStatus

    return SemanticSnapshot(
        observation_id=observation_id,
        version=version,
        session_key=session_key,
        page_key=page_key,
        scene_version=scene_version,
        budget=BudgetManifest(profile_id="semantic", profile_version="2"),
        redaction=RedactionStatus.REDACTED,
    )
