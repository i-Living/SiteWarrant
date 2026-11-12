from playwright.async_api import Page
from pydantic import BaseModel

# A full-page shot of a very long page is a memory spike with no extra information for an
# auditor, so the capture is clipped and the clipping is recorded.
MAX_SCREENSHOT_HEIGHT_PX = 4000


class Screenshot(BaseModel):
    png: bytes
    width: int
    height: int
    clipped: bool


async def capture(page: Page) -> Screenshot:
    metrics = await page.evaluate(
        "() => ({ width: document.documentElement.scrollWidth,"
        " height: document.documentElement.scrollHeight,"
        " viewport_width: window.innerWidth })"
    )
    height = int(metrics["height"])
    clipped = height > MAX_SCREENSHOT_HEIGHT_PX
    shot = await page.screenshot(
        full_page=True,
        clip={
            "x": 0,
            "y": 0,
            "width": int(metrics["viewport_width"]),
            "height": min(height, MAX_SCREENSHOT_HEIGHT_PX),
        },
    )
    return Screenshot(
        png=shot,
        width=int(metrics["viewport_width"]),
        height=min(height, MAX_SCREENSHOT_HEIGHT_PX),
        clipped=clipped,
    )
