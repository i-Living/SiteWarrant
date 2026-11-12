from pathlib import Path
from typing import Any, cast

from playwright.async_api import Page
from pydantic import BaseModel

AXE_VERSION = "4.14.0"
AXE_SOURCE_PATH = Path(__file__).parent / "vendor" / "axe.min.js"
MAX_NODES = 10
EXCERPT_LIMIT = 300

RUN_SCRIPT = f"""async () => {{
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
      failure_summary: node.failureSummary ?? null,
    }})),
  }}));
}}"""


class AxeNode(BaseModel):
    html: str
    target: list[str]
    failure_summary: str | None = None


class AxeViolation(BaseModel):
    id: str
    impact: str | None = None
    help: str
    help_url: str
    tags: list[str]
    nodes: list[AxeNode]


async def run_axe(page: Page) -> list[AxeViolation]:
    """Inject the vendored axe-core build and return its violations."""
    await page.add_script_tag(content=AXE_SOURCE_PATH.read_text(encoding="utf-8"))
    raw = await page.evaluate(RUN_SCRIPT)
    return [AxeViolation.model_validate(item) for item in cast(list[Any], raw)]
