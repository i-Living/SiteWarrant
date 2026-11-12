from collections import Counter, deque
from contextlib import suppress
from datetime import UTC, datetime
from urllib.parse import urldefrag, urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from protego import Protego

from app.core.config import Settings
from app.core.urls import page_key
from app.core.version import compute_agent_version
from app.crawl.links import is_crawlable, parse_html
from app.crawl.models import (
    CrawlLimits,
    CrawlReport,
    DiscoveredPage,
    PageSource,
    TemplateCoverage,
)
from app.crawl.sitemap import sitemap_urls
from app.crawl.templates import template_pattern
from app.tools.fetch import IDLE_TIMEOUT_MS
from app.tools.guard import install_request_guard, pinning_argument
from app.tools.http_get import HttpGetBlocked, HttpGetFailed, http_get, is_html
from app.tools.robots import fetch_robots

MAX_RENDERED_PAGES = 5


class CrawlFailed(RuntimeError):
    """The crawl could not start: the start URL itself is refused or unreachable."""


def normalize_url(url: str) -> str:
    """Drop the fragment: it never reaches the server, so it cannot identify a page."""
    return urldefrag(url.strip())[0]


def same_host(url: str, host: str) -> bool:
    """Discovery stays inside the audited host set; a link elsewhere is not followed."""
    candidate = urlsplit(url).hostname
    return candidate is not None and candidate.lower() == host.lower()


async def render_links(
    url: str, settings: Settings, *, allowed_private_hosts: frozenset[str]
) -> list[str]:
    """Read the links of a page that builds them in JavaScript.

    Only used when the fetched body has neither text nor links: an app shell. The browser
    runs under the same request guard and host pinning as an audit.
    """
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
            _session, blocked = await install_request_guard(
                page, allowed_private_hosts=allowed_private_hosts
            )
            try:
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=settings.page_timeout_ms
                )
            except PlaywrightError as error:
                if blocked:
                    raise HttpGetBlocked(
                        f"request guard blocked {len(blocked)} request(s) on {url}"
                    ) from error
                raise HttpGetFailed(f"{url} did not render: {error}") from error
            with suppress(PlaywrightTimeoutError):
                await page.wait_for_load_state("networkidle", timeout=IDLE_TIMEOUT_MS)
            html = await page.content()
        finally:
            await browser.close()
    return parse_html(html, url).links


async def policy_for(
    url: str,
    settings: Settings,
    *,
    allowed_private_hosts: frozenset[str],
    cache: dict[str, Protego | None],
) -> Protego | None:
    """robots.txt per host, fetched once per crawl.

    A host that answers 5xx raises RobotsUnavailable and the crawl fails: an unknown policy
    is a refusal, not a permission.
    """
    host = (urlsplit(url).hostname or "").lower()
    if host not in cache:
        cache[host] = await fetch_robots(
            url, settings.user_agent, allowed_private_hosts=allowed_private_hosts
        )
    return cache[host]


def select_pages(pages: list[DiscoveredPage], limits: CrawlLimits) -> int:
    """Mark the pages worth auditing and record why the rest were left out.

    Two limits apply: a hard cap on the run and a cap per template, so one large template
    cannot crowd out the rest of the site. Order is discovery order, so the result is
    reproducible for the same site.
    """
    per_template: Counter[str] = Counter()
    selected = 0
    for page in pages:
        if page.skip_reason is not None:
            continue
        if selected >= limits.max_pages:
            page.skip_reason = "page_limit"
            continue
        if per_template[page.template] >= limits.pages_per_template:
            page.skip_reason = "template_limit"
            continue
        page.selected = True
        per_template[page.template] += 1
        selected += 1
    return selected


async def crawl(
    start_url: str,
    *,
    limits: CrawlLimits,
    settings: Settings,
    allowed_private_hosts: frozenset[str],
    ignore_robots: bool = False,
    render_empty_bodies: bool = True,
) -> CrawlReport:
    """Breadth-first discovery from one URL, bounded on every axis.

    robots.txt is consulted per URL, the sitemap and every link are re-validated against
    the host set, and nothing is fetched without the SSRF guard.
    """
    start = normalize_url(start_url)
    host = urlsplit(start).hostname or ""
    if not host:
        raise ValueError(f"{start_url} has no host to crawl")

    queue: deque[tuple[str, int, PageSource]] = deque()
    if limits.include_sitemap:
        for loc in await sitemap_urls(
            start,
            user_agent=settings.user_agent,
            allowed_private_hosts=allowed_private_hosts,
            timeout_s=settings.page_timeout_ms / 1000,
        ):
            if is_crawlable(loc) and same_host(loc, host):
                queue.append((normalize_url(loc), 1, "sitemap"))
    queue.appendleft((start, 0, "start"))

    seen: set[str] = set()
    pages: list[DiscoveredPage] = []
    policies: dict[str, Protego | None] = {}
    rendered = 0

    while queue and len(pages) < limits.max_discovered:
        url, depth, source = queue.popleft()
        key = page_key(url)
        if key in seen:
            continue
        seen.add(key)
        template = template_pattern(url)

        if not ignore_robots:
            policy = await policy_for(
                url, settings, allowed_private_hosts=allowed_private_hosts, cache=policies
            )
            if policy is not None and not policy.can_fetch(url, settings.user_agent):
                pages.append(
                    DiscoveredPage(
                        url=url,
                        page_key=key,
                        template=template,
                        depth=depth,
                        source=source,
                        skip_reason="robots",
                    )
                )
                continue

        try:
            response = await http_get(
                url,
                user_agent=settings.user_agent,
                allowed_private_hosts=allowed_private_hosts,
                timeout_s=settings.page_timeout_ms / 1000,
            )
        except HttpGetBlocked:
            pages.append(
                DiscoveredPage(
                    url=url,
                    page_key=key,
                    template=template,
                    depth=depth,
                    source=source,
                    skip_reason="blocked",
                )
            )
            continue
        except HttpGetFailed:
            pages.append(
                DiscoveredPage(
                    url=url,
                    page_key=key,
                    template=template,
                    depth=depth,
                    source=source,
                    skip_reason="fetch_failed",
                )
            )
            continue

        final_key = page_key(response.url)
        if response.status_code >= 400:
            pages.append(
                DiscoveredPage(
                    url=response.url,
                    page_key=final_key,
                    template=template_pattern(response.url),
                    depth=depth,
                    source=source,
                    status_code=response.status_code,
                    skip_reason=f"http_{response.status_code}",
                )
            )
            continue
        if not is_html(response.content_type):
            pages.append(
                DiscoveredPage(
                    url=response.url,
                    page_key=final_key,
                    template=template_pattern(response.url),
                    depth=depth,
                    source=source,
                    status_code=response.status_code,
                    skip_reason="not_html",
                )
            )
            continue

        parsed = parse_html(response.text, response.url)
        did_render = False
        if (
            render_empty_bodies
            and not parsed.has_text
            and not parsed.links
            and rendered < MAX_RENDERED_PAGES
        ):
            rendered += 1
            did_render = True
            try:
                rendered_links = await render_links(
                    response.url, settings, allowed_private_hosts=allowed_private_hosts
                )
            except (HttpGetBlocked, HttpGetFailed):
                rendered_links = []
            parsed = parsed.model_copy(
                update={"links": list(dict.fromkeys([*parsed.links, *rendered_links]))}
            )

        pages.append(
            DiscoveredPage(
                url=response.url,
                page_key=final_key,
                template=template_pattern(response.url),
                depth=depth,
                source=source,
                status_code=response.status_code,
                rendered=did_render,
                skip_reason="body_too_large" if response.truncated else None,
            )
        )

        if response.truncated or depth >= limits.max_depth or parsed.nofollow:
            continue
        for link in parsed.links:
            if same_host(link, host):
                queue.append((link, depth + 1, "link"))

    start_page = next((page for page in pages if page.source == "start"), None)
    if start_page is None or start_page.skip_reason is not None:
        reason = start_page.skip_reason if start_page is not None else "not reached"
        raise CrawlFailed(f"start URL {start} could not be crawled: {reason}")

    selected = select_pages(pages, limits)
    discovered_by_template = Counter(page.template for page in pages)
    selected_by_template = Counter(page.template for page in pages if page.selected)
    skipped = Counter(page.skip_reason for page in pages if page.skip_reason is not None)

    return CrawlReport(
        site=host,
        start_url=start,
        agent_version=compute_agent_version(
            viewports=settings.viewport_list,
            page_timeout_ms=settings.page_timeout_ms,
            capture_timeout_ms=settings.capture_timeout_ms,
            user_agent=settings.user_agent,
        ),
        generated_at=datetime.now(UTC),
        limits=limits,
        pages_discovered=len(pages),
        pages_selected=selected,
        skipped=dict(sorted(skipped.items())),
        templates=[
            TemplateCoverage(
                template=template,
                discovered=discovered_by_template[template],
                selected=selected_by_template[template],
            )
            for template in sorted(discovered_by_template)
        ],
        pages=pages,
    )
