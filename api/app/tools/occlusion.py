from playwright.async_api import Page
from pydantic import BaseModel

MAX_ITEMS = 20
INTERACTIVE = "a[href], button, input, select, textarea, [role='button'], [role='link']"

PROBE_SCRIPT = f"""() => {{
  const MAX = {MAX_ITEMS};
  // Root-anchored on purpose: a chain truncated at a fixed depth can name two elements in two
  // identical subtrees, and the repair would restyle both. An nth-of-type chain from `html` names
  // exactly one element by construction.
  const path = (el) => {{
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1) {{
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
  // The element under the pointer is often a child of the element that is positioned over the
  // target: the label inside an absolutely positioned banner, not the banner. A repair has to move
  // the element that carries the position, so the probe records it instead of leaving the fixer to
  // guess from a tag name.
  const positioned = (el) => {{
    let node = el;
    while (node && node.nodeType === 1) {{
      const style = getComputedStyle(node);
      const fixed = style.position === 'absolute' || style.position === 'fixed';
      if (fixed || style.position === 'sticky') {{
        return node;
      }}
      node = node.parentElement;
    }}
    return el;
  }};
  const hits = [];
  for (const element of document.querySelectorAll("{INTERACTIVE}")) {{
    const style = getComputedStyle(element);
    if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity) === 0) {{
      continue;
    }}
    const rect = element.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) continue;
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    if (x < 0 || y < 0 || x > window.innerWidth || y > window.innerHeight) continue;
    const top = document.elementFromPoint(x, y);
    if (!top) continue;
    if (top === element || element.contains(top) || top.contains(element)) continue;
    const cover = positioned(top);
    hits.push({{
      selector: path(element),
      tag: element.tagName.toLowerCase(),
      occluder_selector: path(top),
      occluder_tag: top.tagName.toLowerCase(),
      occluder_positioned_selector: path(cover),
      occluder_positioned_tag: cover.tagName.toLowerCase(),
    }});
    if (hits.length >= MAX) break;
  }}
  return hits;
}}"""


class OccludedTarget(BaseModel):
    """An interactive element whose centre point is covered by another element.

    Hit-testing is the measurement: no heuristic about "what looks covered". A target that
    cannot be clicked at its own centre is unreachable for a pointer user, which is what the
    observation claims — nothing more.
    """

    selector: str
    tag: str
    occluder_selector: str
    occluder_tag: str
    # The element that carries the position (an ancestor of the one under the pointer). Empty on
    # payloads recorded before the probe learned to look for it.
    occluder_positioned_selector: str = ""
    occluder_positioned_tag: str = ""


async def probe(page: Page) -> list[OccludedTarget]:
    raw = await page.evaluate(PROBE_SCRIPT)
    return [OccludedTarget.model_validate(item) for item in raw]
