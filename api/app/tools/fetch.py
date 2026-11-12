import time
from contextlib import suppress

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from pydantic import BaseModel

from app.core.config import Settings
from app.tools import dom_probe
from app.tools.axe import AxeViolation, run_axe
from app.tools.dom_probe import DomSnapshot
from app.tools.guard import install_request_guard

IDLE_TIMEOUT_MS = 5_000


class BlockedRequestError(RuntimeError):
    """The request guard refused a URL, usually a private address."""


class Capture(BaseModel):
    url: str
    status_code: int
    html: str
    dom: DomSnapshot
    axe: list[AxeViolation]
    duration_ms: int


async def capture_page(url: str, settings: Settings, *, allow_private: bool) -> Capture:
    started = time.monotonic()
    width, height = settings.viewport_size
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            context = await browser.new_context(
                viewport={"width": width, "height": height},
                user_agent=settings.user_agent,
            )
            blocked = await install_request_guard(context, allow_private=allow_private)
            page = await context.new_page()
            try:
                response = await page.goto(
                    url, wait_until="domcontentloaded", timeout=settings.page_timeout_ms
                )
            except PlaywrightError as error:
                if blocked:
                    raise BlockedRequestError(
                        f"request guard blocked {len(blocked)} request(s), first: {blocked[0]}"
                    ) from error
                raise
            # Pages with long polling never go idle; the DOM is already there.
            with suppress(PlaywrightTimeoutError):
                await page.wait_for_load_state("networkidle", timeout=IDLE_TIMEOUT_MS)
            html = await page.content()
            dom = await dom_probe.probe(page)
            violations = await run_axe(page)
            status_code = response.status if response is not None else 0
            final_url = page.url
        finally:
            await browser.close()
    return Capture(
        url=final_url,
        status_code=status_code,
        html=html,
        dom=dom,
        axe=violations,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
