import asyncio
from contextlib import suppress

from playwright.async_api import Browser, Page, async_playwright
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel

from app.core.config import Settings, viewport_size
from app.tools import contrast, dom_probe, occlusion, performance, responsive, screenshot
from app.tools.axe import AxeViolation, run_axe
from app.tools.contrast import ContrastReport
from app.tools.dom_probe import DomSnapshot
from app.tools.guard import install_request_guard, pinning_argument
from app.tools.occlusion import OccludedTarget
from app.tools.performance import PerformanceFacts
from app.tools.responsive import ResponsiveReport
from app.tools.screenshot import Screenshot

IDLE_TIMEOUT_MS = 5_000


class BlockedRequestError(RuntimeError):
    """The request guard refused a URL, usually a private address."""


class CaptureTimeout(RuntimeError):
    """A page-side operation did not settle within the capture deadline."""


class ViewportCapture(BaseModel):
    """Every fact one viewport produced for one page.

    The channels stay separate rather than merging into one blob: a finding cites the
    observation it rests on, and that observation has to name the viewport it measured.
    """

    viewport: str
    url: str
    status_code: int
    html: str
    dom: DomSnapshot
    axe: list[AxeViolation]
    contrast: ContrastReport
    responsive: ResponsiveReport
    occlusion: list[OccludedTarget]
    performance: PerformanceFacts
    screenshot: Screenshot


class PageCapture(BaseModel):
    url: str
    status_code: int
    viewports: list[ViewportCapture]


Collected = tuple[
    str,
    DomSnapshot,
    ContrastReport,
    ResponsiveReport,
    list[OccludedTarget],
    PerformanceFacts,
    list[AxeViolation],
    Screenshot,
]


async def collect(page: Page, timeout_s: float) -> Collected:
    """Run every page-side channel under one deadline.

    A page can return a promise that never settles, for example an axe run stuck on a
    layout thrash. The navigation timeout does not bound that, so collection is bounded
    here and the caller still closes the browser in its finally block. The screenshot is
    taken last, after every measurement that reads geometry.
    """

    async def gather() -> Collected:
        html = await page.content()
        # The interval closes here: every probe below executes script, and its long tasks are
        # the auditor's work rather than the page's.
        await performance.mark_measurement_end(page)
        dom = await dom_probe.probe(page)
        contrast_report = await contrast.probe(page)
        responsive_report = await responsive.probe(page)
        occluded = await occlusion.probe(page)
        performance_facts = await performance.probe(page)
        violations = await run_axe(page)
        shot = await screenshot.capture(page)
        return (
            html,
            dom,
            contrast_report,
            responsive_report,
            occluded,
            performance_facts,
            violations,
            shot,
        )

    return await asyncio.wait_for(gather(), timeout=timeout_s)


async def capture_viewport(
    browser: Browser,
    url: str,
    settings: Settings,
    viewport: str,
    *,
    allowed_private_hosts: frozenset[str],
) -> ViewportCapture:
    width, height = viewport_size(viewport)
    context = await browser.new_context(
        viewport={"width": width, "height": height},
        user_agent=settings.user_agent,
    )
    try:
        page = await context.new_page()
        # The observer has to exist before the first paint, or LCP and CLS are never recorded.
        await page.add_init_script(performance.INIT_SCRIPT)
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
            (
                html,
                dom,
                contrast_report,
                responsive_report,
                occluded,
                performance_facts,
                violations,
                shot,
            ) = await collect(page, timeout_s=settings.capture_timeout_ms / 1000)
        except TimeoutError as error:
            raise CaptureTimeout(
                f"{viewport} did not settle within {settings.capture_timeout_ms} ms"
            ) from error
        status_code = response.status if response is not None else 0
        final_url = page.url
    finally:
        await context.close()
    return ViewportCapture(
        viewport=viewport,
        url=final_url,
        status_code=status_code,
        html=html,
        dom=dom,
        axe=violations,
        contrast=contrast_report,
        responsive=responsive_report,
        occlusion=occluded,
        performance=performance_facts,
        screenshot=shot,
    )


async def capture_page(
    url: str, settings: Settings, *, allowed_private_hosts: frozenset[str]
) -> PageCapture:
    """Capture the same page at every configured viewport.

    One browser, one context per viewport: contexts are isolated, so a viewport cannot
    inherit cookies, storage or a resized layout from the previous one.
    """
    launch_args = await pinning_argument(url)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(args=launch_args)
        try:
            captures = [
                await capture_viewport(
                    browser,
                    url,
                    settings,
                    viewport,
                    allowed_private_hosts=allowed_private_hosts,
                )
                for viewport in settings.viewport_list
            ]
        finally:
            await browser.close()
    return PageCapture(
        url=captures[0].url,
        status_code=captures[0].status_code,
        viewports=captures,
    )
