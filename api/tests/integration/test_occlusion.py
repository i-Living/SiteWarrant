"""The occlusion probe names the element that carries the offset, not the pointer's element."""

from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from app.fixes.reaudit import PatchedSite
from app.tools.occlusion import probe

pytestmark = pytest.mark.integration

# A banner that never leaves the flow but is pulled up over the paragraph above it. The element
# under the pointer at the link's centre is the banner itself; the point is that the probe reports
# it as the occluder, because `position: static !important` on a child would move nothing.
PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>relative banner</title>
<style>
  body { margin: 0; font: 16px/1.4 sans-serif; }
  main { padding: 20px; }
  .banner { position: relative; top: -64px; margin-bottom: -64px; background: #112233; color: #fff;
            padding: 8px; }
  a { display: inline-block; padding: 4px; }
</style></head>
<body><main>
  <p><a href="/one">first link</a></p>
  <div class="banner">promo <a href="/two">inside</a></div>
  <p><a href="/three">third link</a></p>
</main></body></html>
"""


async def test_a_relative_banner_that_covers_a_link_is_the_named_occluder(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(PAGE, encoding="utf-8")
    with PatchedSite(tmp_path) as server:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            page = await browser.new_page(viewport={"width": 900, "height": 700})
            await page.goto(f"{server.base_url}/index.html")
            hits = await probe(page)
            await browser.close()

    assert [hit.tag for hit in hits] == ["a"]
    hit = hits[0]
    # `relative` with an inset carries the offset as surely as `absolute` does; a plain wrapper
    # with every inset `auto` does not, which is why the probe looks at the insets.
    assert hit.occluder_positioned_selector == (
        "html:nth-of-type(1) > body:nth-of-type(1) > main:nth-of-type(1) > div:nth-of-type(1)"
    )
    assert hit.occluder_positioned_tag == "div"
    assert hit.selector.endswith("p:nth-of-type(1) > a:nth-of-type(1)")
