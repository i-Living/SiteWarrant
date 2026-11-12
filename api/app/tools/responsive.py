from playwright.async_api import Page
from pydantic import BaseModel

# WCAG 2.2 SC 2.5.8 Target Size (Minimum): 24 by 24 CSS pixels.
TOUCH_TARGET_MIN_PX = 24.0
MAX_ITEMS = 10
INTERACTIVE = "a[href], button, input, select, textarea, [role='button'], [role='link']"

PROBE_SCRIPT = f"""() => {{
  const MAX = {MAX_ITEMS};
  const path = (el) => {{
    const parts = [];
    let node = el;
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
  const overflowing = [];
  const small = [];
  for (const element of document.querySelectorAll('body *')) {{
    const style = getComputedStyle(element);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    const rect = element.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) continue;
    if (rect.right > window.innerWidth + 1 && overflowing.length < MAX) {{
      overflowing.push({{
        selector: path(element),
        tag: element.tagName.toLowerCase(),
        right_px: rect.right,
        width_px: rect.width,
      }});
    }}
    if (element.matches("{INTERACTIVE}") && small.length < MAX) {{
      if (rect.width < {TOUCH_TARGET_MIN_PX} || rect.height < {TOUCH_TARGET_MIN_PX}) {{
        small.push({{
          selector: path(element),
          tag: element.tagName.toLowerCase(),
          width_px: rect.width,
          height_px: rect.height,
        }});
      }}
    }}
  }}
  return {{
    viewport_width: window.innerWidth,
    document_width: document.documentElement.scrollWidth,
    overflowing: overflowing,
    small_targets: small,
  }};
}}"""


class OverflowItem(BaseModel):
    """A measured box, unrounded: rounding 390.4 to 391 would invent an overflow."""

    selector: str
    tag: str
    right_px: float
    width_px: float


class TouchTarget(BaseModel):
    selector: str
    tag: str
    width_px: float
    height_px: float


class ResponsiveReport(BaseModel):
    """Geometry facts for one viewport. Widths are CSS pixels, not device pixels."""

    viewport_width: int
    document_width: int
    overflowing: list[OverflowItem]
    small_targets: list[TouchTarget]


def has_horizontal_overflow(report: ResponsiveReport) -> bool:
    return report.document_width > report.viewport_width + 1


def overflow_px(report: ResponsiveReport) -> int:
    """How far the document exceeds the viewport, with one pixel of rounding allowed."""
    if not has_horizontal_overflow(report):
        return 0
    return report.document_width - report.viewport_width


async def probe(page: Page) -> ResponsiveReport:
    raw = await page.evaluate(PROBE_SCRIPT)
    return ResponsiveReport.model_validate(raw)
