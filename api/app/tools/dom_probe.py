from playwright.async_api import Page
from pydantic import BaseModel

PROBE_SCRIPT = """() => {
  const description = document.querySelector('meta[name="description"]');
  const canonical = document.querySelector('link[rel="canonical"]');
  const lang = document.documentElement.getAttribute('lang');
  return {
    url: location.href,
    title: (document.title || '').trim(),
    meta_description: description ? (description.getAttribute('content') || '').trim() : null,
    h1_count: document.querySelectorAll('h1').length,
    lang: lang ? lang.trim() : null,
    canonical: canonical ? canonical.getAttribute('href') : null,
  };
}"""


class DomSnapshot(BaseModel):
    url: str
    title: str = ""
    meta_description: str | None = None
    h1_count: int = 0
    lang: str | None = None
    canonical: str | None = None


async def probe(page: Page) -> DomSnapshot:
    """Read the facts a page exposes without a model in the loop."""
    raw = await page.evaluate(PROBE_SCRIPT)
    return DomSnapshot.model_validate(raw)
