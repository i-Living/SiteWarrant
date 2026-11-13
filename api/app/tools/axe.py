from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from playwright.async_api import Page
from pydantic import BaseModel

AXE_VERSION = "4.14.0"
AXE_SOURCE_PATH = Path(__file__).parent / "vendor" / "axe.min.js"
MAX_NODES = 10
EXCERPT_LIMIT = 300

RUN_SCRIPT = f"""async () => {{
  const pathOf = (selector) => {{
    let element = null;
    try {{ element = document.querySelector(selector); }} catch (error) {{ return null; }}
    if (!element) return null;
    const parts = [];
    let node = element;
    while (node && node.nodeType === 1 && parts.length < 6) {{
      const parent = node.parentElement;
      let index = 1;
      if (parent) {{
        for (const sibling of parent.children) {{
          if (sibling === node) break;
          if (sibling.tagName === node.tagName) index += 1;
        }}
      }}
      parts.unshift(node.tagName.toLowerCase() + ':nth-of-type(' + index + ')');
      node = parent;
    }}
    return parts.join(' > ');
  }};
  const results = await axe.run(document, {{ resultTypes: ['violations'] }});
  return results.violations.map((violation) => ({{
    id: violation.id,
    impact: violation.impact ?? null,
    help: violation.help,
    help_url: violation.helpUrl,
    tags: violation.tags,
    nodes: violation.nodes.slice(0, {MAX_NODES}).map((node) => ({{
      html: node.html.slice(0, {EXCERPT_LIMIT}),
      target: node.target.map(String),
      path: pathOf(node.target[0]),
      failure_summary: node.failureSummary ?? null,
    }})),
  }}));
}}"""


class AxeNode(BaseModel):
    html: str
    target: list[str]
    # The element's own DOM path: axe reports a CSS selector, which names no place.
    path: str | None = None
    failure_summary: str | None = None


class AxeViolation(BaseModel):
    id: str
    impact: str | None = None
    help: str
    help_url: str
    tags: list[str]
    nodes: list[AxeNode]


@lru_cache(maxsize=1)
def axe_source() -> str:
    return AXE_SOURCE_PATH.read_text(encoding="utf-8")


async def run_axe(page: Page) -> list[AxeViolation]:
    """Inject the vendored axe-core build and return its violations.

    The build goes in through Runtime.evaluate, not through add_script_tag: a page with a
    strict script-src policy rejects an inline script element and the whole audit would
    fail, while Runtime.evaluate is not subject to that policy. Pinned by the CSP fixture.
    """
    await page.evaluate(axe_source())
    raw = await page.evaluate(RUN_SCRIPT)
    return [AxeViolation.model_validate(item) for item in cast(list[Any], raw)]
