import asyncio
import time
from contextlib import suppress

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel

from app.core.config import Settings
from app.tools import dom_probe
from app.tools.axe import AxeViolation, run_axe
from app.tools.dom_probe import DomSnapshot
from app.tools.guard import install_request_guard, pinning_argument

IDLE_TIMEOUT_MS = 5_000


class BlockedRequestError(RuntimeError):
    """The request guard refused a URL, usually a private address."""


class CaptureTimeout(RuntimeError):
    """A page-side operation did not settle within the capture deadline."""


class Capture(BaseModel):
    url: str
    status_code: int
    html: str
    dom: DomSnapshot
    axe: list[AxeViolation]
    duration_ms: int


async def collect(page: Page, timeout_s: float) -> tuple[str, DomSnapshot, list[AxeViolation]]:
    """Run the page-side work under one deadline.

    A page can return a promise that never settles, for example an axe run stuck on a
    layout thrash. The navigation timeout does not bound that, so collection is bounded
    here and the caller still closes the browser in its finally block.
    """

    async def gather() -> tuple[str, DomSnapshot, list[AxeViolation]]:
        html = await page.content()
        dom = await dom_probe.probe(page)
        violations = await run_axe(page)
        return html, dom, violations

    return await asyncio.wait_for(gather(), timeout=timeout_s)


async def capture_page(
    url: str, settings: Settings, *, allowed_private_hosts: frozenset[str]
) -> Capture:
    started = time.monotonic()
    width, height = settings.viewport_size
    launch_args = await pinning_argument(url)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(args=launch_args)
        try:
            context = await browser.new_context(
                viewport={"width": width, "height": height},
                user_agent=settings.user_agent,
            )
            page = await context.new_page()
            _guard_session, blocked = await install_request_guard(
                page, allowed_private_hosts=allowed_private_hosts
            )
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
            try:
                html, dom, violations = await collect(
                    page, timeout_s=settings.capture_timeout_ms / 1000
                )
            except TimeoutError as error:
                raise CaptureTimeout(
                    f"page did not settle within {settings.capture_timeout_ms} ms"
                ) from error
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
