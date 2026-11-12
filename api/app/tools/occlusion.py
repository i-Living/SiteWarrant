from playwright.async_api import Page
from pydantic import BaseModel

MAX_ITEMS = 20
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
  const hits = [];
  for (const element of document.querySelectorAll("{INTERACTIVE}")) {{
    const rect = element.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) continue;
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    if (x < 0 || y < 0 || x > window.innerWidth || y > window.innerHeight) continue;
    const top = document.elementFromPoint(x, y);
    if (!top) continue;
    if (top === element || element.contains(top) || top.contains(element)) continue;
    hits.push({{
      selector: path(element),
      tag: element.tagName.toLowerCase(),
      occluder_selector: path(top),
      occluder_tag: top.tagName.toLowerCase(),
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


async def probe(page: Page) -> list[OccludedTarget]:
    raw = await page.evaluate(PROBE_SCRIPT)
    return [OccludedTarget.model_validate(item) for item in raw]
