from playwright.async_api import Page

from agentqa.contracts import ObservationSnapshot

MAX_OBSERVATION_BYTES = 8192

_ELEMENTS_JS = """
els => els.map(e => ({
  tag: e.tagName.toLowerCase(),
  id: e.id || "",
  text: (e.innerText || e.value || e.placeholder || e.getAttribute("aria-label") || "")
          .trim().slice(0, 80)
}))
"""


async def observe(page: Page, mode: str = "a11y") -> ObservationSnapshot:
    url = page.url
    title = await page.title()
    elements = await page.eval_on_selector_all("a, button, input, select, textarea", _ELEMENTS_JS)
    body_text = (await page.inner_text("body")).strip()
    lines = [f"- {e['tag']}#{e['id']}: {e['text']}" for e in elements]
    text = (
        f"URL: {url}\nTITLE: {title}\n"
        f"ELEMENTS ({len(elements)}):\n" + "\n".join(lines) + "\nPAGE TEXT:\n" + body_text
    )
    encoded = text.encode("utf-8")
    truncated = len(encoded) > MAX_OBSERVATION_BYTES
    if truncated:
        text = encoded[:MAX_OBSERVATION_BYTES].decode("utf-8", errors="ignore")
    return ObservationSnapshot(
        mode=mode,
        url=url,
        title=title,
        text=text,
        element_count=len(elements),
        size_bytes=min(len(encoded), MAX_OBSERVATION_BYTES),
        truncated=truncated,
    )
