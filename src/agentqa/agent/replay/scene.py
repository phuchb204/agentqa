from __future__ import annotations

from typing import Any

from agentqa.agent.browser.contexts import ContextRegistry
from agentqa.agent.identity.resolver import SceneCandidate

SCENE_SCRIPT = """
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
    if (tag === 'li') return 'listitem';
    if (['h1', 'h2', 'h3', 'h4', 'h5', 'h6'].includes(tag)) return 'heading';
    if (tag === 'form') return 'form';
    return tag;
  };
  const nodes = Array.from(
    document.querySelectorAll('button,a,input,select,textarea,li,h1,h2,h3,[role]')
  ).slice(0, 300);
  return nodes.map((el, index) => {
    const attributes = {};
    for (const name of ['id', 'name', 'data-testid', 'data-item-id']) {
      const value = el.getAttribute(name);
      if (value !== null) attributes[name] = value;
    }
    const label = el.labels && el.labels.length ? el.labels[0].textContent : null;
    if (label) attributes['label'] = label.trim();
    const accessible = el.getAttribute('aria-label')
      || (label ? label.trim() : '')
      || (el.textContent || '').trim();
    const row = el.closest('li');
    return {
      candidate_id: 'c' + index,
      role: roleOf(el),
      name: accessible.slice(0, 120),
      text: (el.textContent || '').trim().slice(0, 200),
      visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
      enabled: !el.disabled,
      attributes,
      entity_text: row ? (row.textContent || '').trim().slice(0, 200) : null,
    };
  });
}
"""


class PlaywrightSceneProvider:
    def __init__(self, contexts: ContextRegistry) -> None:
        self._contexts = contexts

    async def scene(self, context_key: str) -> list[SceneCandidate]:
        page = await self._contexts.page(context_key)
        raw: list[dict[str, Any]] = await page.evaluate(SCENE_SCRIPT)
        return [
            SceneCandidate(
                candidate_id=item["candidate_id"],
                role=item.get("role"),
                name=item.get("name"),
                text=item.get("text"),
                visible=bool(item.get("visible", True)),
                enabled=bool(item.get("enabled", True)),
                attributes=dict(item.get("attributes", {})),
                entity_text=item.get("entity_text"),
            )
            for item in raw
        ]
