from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from uuid import UUID

from agentqa.agent.observation.provenance import (
    InputAuditor,
    NullRedactor,
    Redactor,
    TaintChecks,
    max_taint,
)
from agentqa.agent.observation.selection import DEFAULT_SEMANTIC_PROFILE, BudgetSelector
from agentqa.contracts.observation import (
    Actionability,
    BudgetProfile,
    CandidateState,
    Modality,
    ModalityAudit,
    RedactionStatus,
    SemanticCandidate,
    SemanticSnapshot,
)
from agentqa.contracts.values import Taint

SEMANTIC_CAPTURE_VERSION = 2

SEMANTIC_CAPTURE_SCRIPT = """
() => {
  const roleOf = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'input') {
      const type = (el.getAttribute('type') || 'text').toLowerCase();
      if (['button', 'submit', 'reset'].includes(type)) return 'button';
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      return 'textbox';
    }
    if (tag === 'button') return 'button';
    if (tag === 'a') return 'link';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'img') return 'img';
    if (tag === 'canvas') return 'canvas';
    if (tag === 'li') return 'listitem';
    if (tag === 'form') return 'form';
    return tag;
  };
  const actionabilityOf = (el, visible) => {
    if (el.disabled) return 'disabled';
    if (!visible) return 'offscreen';
    const style = window.getComputedStyle(el);
    if (style && (style.visibility === 'hidden' || style.pointerEvents === 'none')) return 'obscured';
    return 'actionable';
  };
  const nodes = Array.from(
    document.querySelectorAll('button,a,input,select,textarea,li,img,canvas,h1,h2,h3,form,[role]')
  ).slice(0, 400);
  return {
    url: window.location.href,
    title: document.title || null,
    frame_key: window.frameElement ? (window.frameElement.getAttribute('name') || 'frame') : null,
    scene_version: window.__agentqa_scene_version || 1,
    candidates: nodes.map((el, index) => {
      const rect = el.getBoundingClientRect();
      const label = el.labels && el.labels.length ? el.labels[0].textContent : null;
      const name = el.getAttribute('aria-label') || (label ? label.trim() : '') || (el.textContent || '').trim();
      const row = el.closest('li');
      const attributes = {};
      for (const key of ['id', 'name', 'data-testid', 'data-item-id', 'type']) {
        const value = el.getAttribute(key);
        if (value !== null) attributes[key] = value;
      }
      return {
        source_id: 'n' + index,
        role: roleOf(el),
        name: name.slice(0, 160),
        text: (el.textContent || '').trim().slice(0, 240),
        visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
        enabled: !el.disabled,
        checked: typeof el.checked === 'boolean' ? el.checked : null,
        selected: typeof el.selected === 'boolean' ? el.selected : null,
        expanded: el.getAttribute('aria-expanded') === null ? null : el.getAttribute('aria-expanded') === 'true',
        actionability: actionabilityOf(el, !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)),
        region: el.getAttribute('data-agentqa-region')
          || (row ? 'row:' + (row.getAttribute('data-item-id') || '') : null),
        entity_key: el.getAttribute('data-item-id') || null,
        provenance: 'dom',
        box: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
        attributes,
      };
    }),
  };
}
"""


@dataclass(frozen=True)
class RawCandidate:
    source_id: str
    role: str
    name: str
    text: str = ""
    visible: bool = True
    enabled: bool = True
    checked: bool | None = None
    selected: bool | None = None
    expanded: bool | None = None
    actionability: Actionability = Actionability.UNKNOWN
    region: str | None = None
    entity_key: str | None = None
    provenance: str = "dom"
    box: tuple[float, float, float, float] | None = None
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RawScene:
    url: str
    title: str | None
    scene_version: int
    candidates: list[RawCandidate]
    frame_key: str | None = None


class SceneSource:
    async def read(self, context_key: str) -> RawScene:
        raise NotImplementedError


class StaticSceneSource(SceneSource):
    def __init__(self, scene: RawScene) -> None:
        self.scene = scene

    async def read(self, context_key: str) -> RawScene:
        return self.scene


class PlaywrightSceneSource(SceneSource):
    def __init__(self, contexts) -> None:
        self._contexts = contexts

    async def read(self, context_key: str) -> RawScene:
        page = await self._contexts.page(context_key)
        raw: dict = await page.evaluate(SEMANTIC_CAPTURE_SCRIPT)
        return scene_from_payload(raw)


def scene_from_payload(raw: dict) -> RawScene:
    candidates = [
        RawCandidate(
            source_id=str(item.get("source_id", f"n{index}")),
            role=str(item.get("role", "unknown")),
            name=str(item.get("name", "")),
            text=str(item.get("text", "")),
            visible=bool(item.get("visible", True)),
            enabled=bool(item.get("enabled", True)),
            checked=item.get("checked") if isinstance(item.get("checked"), bool) else None,
            selected=item.get("selected") if isinstance(item.get("selected"), bool) else None,
            expanded=item.get("expanded") if isinstance(item.get("expanded"), bool) else None,
            actionability=_actionability(item.get("actionability")),
            region=item.get("region") if isinstance(item.get("region"), str) else None,
            entity_key=item.get("entity_key") if isinstance(item.get("entity_key"), str) else None,
            provenance="dom",
            box=_box(item.get("box")),
            attributes=dict(item.get("attributes", {})) if isinstance(item.get("attributes"), dict) else {},
        )
        for index, item in enumerate(raw.get("candidates", []))
    ]
    return RawScene(
        url=str(raw.get("url", "")),
        title=raw.get("title") if isinstance(raw.get("title"), str) else None,
        frame_key=raw.get("frame_key") if isinstance(raw.get("frame_key"), str) else None,
        scene_version=int(raw.get("scene_version", 1)),
        candidates=candidates,
    )


class SemanticObservationBuilder:
    def __init__(
        self,
        *,
        profile: BudgetProfile | None = None,
        redactor: Redactor | None = None,
        taint: TaintChecks | None = None,
        auditor: InputAuditor | None = None,
    ) -> None:
        self._selector = BudgetSelector(profile)
        self._redactor = redactor or NullRedactor()
        self._taint = taint
        self._auditor = auditor or InputAuditor(taint=taint, redactor=self._redactor)

    def build(
        self,
        scene: RawScene,
        *,
        observation_id: UUID,
        version: int,
        session_key: str,
        page_key: str,
        subgoal_terms: tuple[str, ...] = (),
        mandatory_ids: frozenset[str] = frozenset(),
    ) -> tuple[SemanticSnapshot, ModalityAudit]:
        candidates = [self._map_candidate(raw, index) for index, raw in enumerate(scene.candidates)]
        selection = self._selector.select(candidates, subgoal_terms=subgoal_terms, mandatory_ids=mandatory_ids)
        taint = max_taint(candidate.taint for candidate in selection.kept)
        snapshot = SemanticSnapshot(
            observation_id=observation_id,
            version=version,
            session_key=session_key,
            page_key=page_key,
            frame_key=scene.frame_key,
            scene_version=scene.scene_version,
            url=self._redactor.redact_text(scene.url),
            title=self._redactor.redact_text(scene.title) if scene.title else None,
            candidates=selection.kept,
            regions=selection.regions,
            budget=selection.manifest,
            redaction=RedactionStatus.REDACTED,
            taint=taint,
        )
        audit = self._auditor.audit(
            observation_id=observation_id,
            modality=Modality.SEMANTIC,
            payload=semantic_payload(snapshot),
            image_bytes=None,
            scene_version=scene.scene_version,
        )
        return snapshot, audit

    def _map_candidate(self, raw: RawCandidate, index: int) -> SemanticCandidate:
        text = raw.text
        name = raw.name
        taint = Taint.PUBLIC
        if self._taint is not None and (self._taint.find(text) or self._taint.find(name)):
            text = ""
            name = ""
            taint = Taint.SECRET
        else:
            text = self._redactor.redact_text(text)
            name = self._redactor.redact_text(name)
        state = CandidateState(
            enabled=raw.enabled,
            checked=raw.checked,
            selected=raw.selected,
            expanded=raw.expanded,
        )
        return SemanticCandidate(
            candidate_id=f"c{index}",
            role=raw.role,
            name=name,
            state=state,
            region=_opaque_region(raw.region),
            visible=raw.visible,
            actionability=raw.actionability,
            text=text,
            entity_key=_opaque_entity(raw.entity_key),
            taint=taint,
            provenance=raw.provenance,
        )


def semantic_payload(snapshot: SemanticSnapshot) -> dict:
    return {
        "observation_id": str(snapshot.observation_id),
        "version": snapshot.version,
        "scene_version": snapshot.scene_version,
        "url": snapshot.url,
        "title": snapshot.title,
        "candidates": [candidate.model_dump(mode="json") for candidate in snapshot.candidates],
        "regions": [region.model_dump(mode="json") for region in snapshot.regions],
        "budget": snapshot.budget.model_dump(mode="json"),
    }


def _actionability(value: object) -> Actionability:
    try:
        return Actionability(str(value))
    except ValueError:
        return Actionability.UNKNOWN


def _box(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        return (
            float(value.get("x", 0)),
            float(value.get("y", 0)),
            float(value.get("width", 0)),
            float(value.get("height", 0)),
        )
    except (TypeError, ValueError):
        return None


def _opaque_entity(entity_key: str | None) -> str | None:
    if not entity_key:
        return None
    return "e" + sha256(entity_key.encode("utf-8")).hexdigest()[:12]


def _opaque_region(region: str | None) -> str | None:
    if not region:
        return None
    kind, _, scope = region.partition(":")
    if not scope:
        return kind
    return f"{kind}:{_opaque_entity(scope)}"


__all__ = [
    "DEFAULT_SEMANTIC_PROFILE",
    "SEMANTIC_CAPTURE_SCRIPT",
    "SEMANTIC_CAPTURE_VERSION",
    "PlaywrightSceneSource",
    "RawCandidate",
    "RawScene",
    "SceneSource",
    "SemanticObservationBuilder",
    "StaticSceneSource",
    "scene_from_payload",
    "semantic_payload",
]
