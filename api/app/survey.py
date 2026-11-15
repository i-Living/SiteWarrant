"""Audit the pages a crawl selected, and merge them into one report for the site.

One page audits itself; a site needs discovery first, because auditing the home page says nothing
about the fifty pages behind it. This module runs the existing per-page audit over the crawl's
selection and merges the results into one artifact, so a site has one `report.json` instead of
fifty (docs/PLAN.md, definition of done §16.1).

It deliberately does not re-cluster across pages. A root cause is a block on a page — two pages that
both carry a `header` do not share a cause, and merging them would invent one neither page has
(docs/PLAN.md section 6, invariant 3). The merged report therefore keeps the per-page causes as they
came, and `pages_audited` says how many pages they describe.

The second shape is a sitemap run: the worker reads /sitemap.xml, queues one ordinary page audit
per entry (bounded) and finishes its own row as the dispatch. A site audit is therefore a batch of
page audits, not a second kind of report — `pages` rows stay per page, and the site ledger keeps one
result per page.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from urllib.parse import urlsplit

from protego import Protego
from pydantic import BaseModel, Field

from app import lifecycle
from app.audit import AuditCancelled, LeaseLost, audit_config, current_agent_version, run_audit
from app.core.config import Settings
from app.core.db import session_scope
from app.core.report import AgentSummaryOut, Report, build_report
from app.core.urls import page_key
from app.crawl.crawler import crawl as crawl_site
from app.crawl.crawler import normalize_url
from app.crawl.links import is_crawlable, same_host
from app.crawl.models import CrawlLimits, CrawlReport
from app.crawl.sitemap import sitemap_urls
from app.storage import repo
from app.tools.robots import fetch_robots, robots_hop_check

FAILURE_CHARS = 300

# A sitemap run is a convenience, not a crawler: ten pages by default, fifty at most, so one
# submission cannot turn into an hour of browsers. The number travels in the audit's config.
SITEMAP_DEFAULT_PAGES = 10
SITEMAP_MAX_PAGES = 50

# The whole discovery — the sitemap and one level of index children, with the root fallback —
# has to finish inside this. `http_get` bounds a read, not the discovery, and a slow-dripping
# sitemap would otherwise hold the dispatch row in `running`.
SITEMAP_TIMEOUT_S = 60.0


class SurveyResult(BaseModel):
    """The merged report, the pages it covers, and what could not be audited."""

    report: Report
    crawl: CrawlReport
    pages: list[str] = Field(default_factory=list)
    failures: list[tuple[str, str]] = Field(default_factory=list)

    @property
    def status(self) -> str:
        """`partial` when a page failed outright or when a page came back partial itself.

        A page audit whose agent failed returns `partial` without raising, so counting only the
        exceptions would call a survey complete while its merged agent row says `failed`.
        """
        return "partial" if self.failures or self.report.status != "completed" else "completed"


def merge_agents(reports: Sequence[Report]) -> list[AgentSummaryOut]:
    """One row per agent name, with the measured totals of every page it ran on.

    Status is `ok` only when every page was `ok`: an agent that failed once did not cover the site,
    and reporting it as ok would be the same lie as dropping the failure.
    """
    merged: dict[str, AgentSummaryOut] = {}
    for report in reports:
        for agent in report.summary.agents:
            seen = merged.get(agent.name)
            if seen is None:
                merged[agent.name] = agent.model_copy()
                continue
            merged[agent.name] = seen.model_copy(
                update={
                    "status": "ok"
                    if seen.status == "ok" and agent.status == "ok"
                    else (seen.status if seen.status != "ok" else agent.status),
                    "cost_estimate_usd": (
                        None
                        if seen.cost_estimate_usd is None or agent.cost_estimate_usd is None
                        else round(seen.cost_estimate_usd + agent.cost_estimate_usd, 6)
                    ),
                    "findings": seen.findings + agent.findings,
                    "rejected": seen.rejected + agent.rejected,
                    "tool_calls": seen.tool_calls + agent.tool_calls,
                    "llm_calls": seen.llm_calls + agent.llm_calls,
                    "tokens_in": seen.tokens_in + agent.tokens_in,
                    "tokens_out": seen.tokens_out + agent.tokens_out,
                    "latency_ms": seen.latency_ms + agent.latency_ms,
                    "error": seen.error or agent.error,
                }
            )
    return list(merged.values())


def merge_reports(
    reports: Sequence[Report],
    *,
    site: str,
    failures: Sequence[tuple[str, str]] = (),
    audit_id: str | None = None,
) -> Report:
    """Concatenate what the pages measured into one report, keeping each page's causes."""
    if not reports:
        raise ValueError("a survey needs at least one audited page")
    first = reports[0]
    findings = [finding for report in reports for finding in report.findings]
    causes = [cause for report in reports for cause in report.root_causes]
    observations: Counter[str] = Counter()
    for report in reports:
        observations.update(report.summary.observations_by_tool)
    measured = {category for report in reports for category in report.summary.scores}
    duplicates = sum(report.summary.duplicates_removed for report in reports)
    page_is_partial = any(report.status != "completed" for report in reports)
    pages = list(dict.fromkeys(page for report in reports for page in report.pages))
    return build_report(
        audit_id=audit_id or str(uuid.uuid4()),
        site=site,
        agent_version=first.agent_version,
        status="partial" if failures or page_is_partial else "completed",
        findings=findings,
        pages_audited=len(reports),
        duration_ms=sum(report.summary.duration_ms for report in reports),
        measured_categories=measured,
        observations_by_tool=dict(observations),
        agents=merge_agents(reports),
        root_causes=causes,
        duplicates_removed=duplicates,
        pricing=first.summary.pricing,
        pages=pages,
    )


async def run_survey(
    url: str,
    *,
    limits: CrawlLimits,
    settings: Settings,
    allowed_private_hosts: frozenset[str],
    allow_private: bool = False,
    ignore_robots: bool = False,
    agents: Sequence[str] = (),
) -> SurveyResult:
    """Discover the site, then audit every page the crawl selected.

    A page that fails is recorded and the survey continues: one broken page out of fifty is a
    partial survey, not a failed one, and the failures are in the result.
    """
    crawl_report = await crawl_site(
        url,
        limits=limits,
        settings=settings,
        allowed_private_hosts=allowed_private_hosts,
        ignore_robots=ignore_robots,
    )
    pages = [page.url for page in crawl_report.pages if page.selected]
    reports: list[Report] = []
    failures: list[tuple[str, str]] = []
    for page_url in pages:
        try:
            reports.append(
                await run_audit(
                    page_url,
                    allow_private=allow_private,
                    ignore_robots=ignore_robots,
                    agents=agents,
                )
            )
        except Exception as error:  # one page must not end the survey
            failures.append((page_url, f"{type(error).__name__}: {error}"[:FAILURE_CHARS]))
    if not reports:
        raise RuntimeError(
            f"no page of {url} could be audited: "
            + "; ".join(f"{page}: {error}" for page, error in failures[:3])
        )
    merged = merge_reports(reports, site=url, failures=failures)
    return SurveyResult(report=merged, crawl=crawl_report, pages=pages, failures=failures)


class SitemapUnavailable(RuntimeError):
    """The site published nothing a sitemap run could audit."""


ProgressFn = Callable[[str], Awaitable[None]]
CancelFn = Callable[[], Awaitable[bool]]


def select_sitemap_pages(
    url: str,
    entries: Sequence[str],
    *,
    max_pages: int,
    policy: Protego | None = None,
    user_agent: str = "",
) -> list[str]:
    """The pages a sitemap run audits: the sitemap's entries, with the submitted URL first.

    Everything here is the guard the crawler already applies to sitemap entries: the entry has
    to be crawlable HTML on the audited host, robots.txt has to allow it (when a policy was
    fetched), and two spellings of one page count once (`page_key`). The cap is on the run, not
    on the sitemap, so a sitemap of five hundred entries costs ten audits by default.

    An empty result means the sitemap yielded nothing this run may audit, and the caller fails
    the dispatch: the submitted URL is only added in front once at least one entry survived,
    because one page audited under a sitemap request would present a fallback as the thing that
    was asked for.
    """
    host = (urlsplit(url).hostname or "").lower()

    def allowed(candidate: str) -> str | None:
        page = normalize_url(candidate)
        if not is_crawlable(page) or not same_host(page, host):
            return None
        if policy is not None and not policy.can_fetch(page, user_agent):
            return None
        return page

    selected: list[str] = []
    seen: set[str] = set()
    for candidate in entries:
        page = allowed(candidate)
        if page is None or page_key(page) in seen:
            continue
        seen.add(page_key(page))
        selected.append(page)
        if len(selected) >= max_pages:
            break
    if not selected:
        return []
    seed = allowed(url)
    if seed is None:
        return selected
    key = page_key(seed)
    # The submitted page is audited first, and in the spelling the operator gave: a sitemap that
    # already lists it must not leave a second spelling ahead of it in the queue.
    selected = [page for page in selected if page_key(page) != key]
    selected.insert(0, seed)
    del selected[max_pages:]
    return selected


async def sitemap_pages(
    url: str,
    *,
    max_pages: int,
    settings: Settings,
    allowed_private_hosts: frozenset[str],
    ignore_robots: bool = False,
    deadline_s: float = SITEMAP_TIMEOUT_S,
) -> list[str]:
    """Read /sitemap.xml and keep the entries this run may audit.

    A site with no sitemap is an error, not a shorter run: answering "one page audited" here would
    present the fallback as the thing that was asked for. An empty sitemap after filtering is the
    same failure with a different cause, so the message names which one it was.

    A sitemap lives at the site root far more often than beside the page that was submitted, so the
    origin's `/sitemap.xml` is tried when the path-relative one publishes nothing: a run pointed at
    `https://example.com/pricing` still walks `https://example.com/sitemap.xml`.
    """
    timeout_s = settings.page_timeout_ms / 1000
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc.strip()}/"
    hop_check = (
        None
        if ignore_robots
        else robots_hop_check(settings.user_agent, allowed_private_hosts=allowed_private_hosts)
    )
    tried = url
    try:
        # `http_get` bounds each read, not the discovery: a sitemap host that drips a byte at a
        # time would keep the dispatch row running and its operator waiting. The aggregate
        # deadline is what bounds it, and a sitemap that misses it fails the dispatch with a
        # reason instead of hanging in `running`.
        async with asyncio.timeout(deadline_s):
            entries = await sitemap_urls(
                url,
                user_agent=settings.user_agent,
                allowed_private_hosts=allowed_private_hosts,
                timeout_s=timeout_s,
                hop_check=hop_check,
            )
            if not entries and page_key(origin) != page_key(url):
                entries = await sitemap_urls(
                    origin,
                    user_agent=settings.user_agent,
                    allowed_private_hosts=allowed_private_hosts,
                    timeout_s=timeout_s,
                    hop_check=hop_check,
                )
                tried = origin
    except TimeoutError as error:
        raise SitemapUnavailable(
            f"reading /sitemap.xml of {url} took longer than {deadline_s:g} s"
        ) from error
    if not entries:
        raise SitemapUnavailable(
            f"{tried} publishes no /sitemap.xml this run may read "
            "(absent, unreadable, or disallowed by robots.txt)"
        )
    policy = (
        None
        if ignore_robots
        else await fetch_robots(
            url, settings.user_agent, allowed_private_hosts=allowed_private_hosts
        )
    )
    pages = select_sitemap_pages(
        url, entries, max_pages=max_pages, policy=policy, user_agent=settings.user_agent
    )
    if not pages:
        raise SitemapUnavailable(
            f"no /sitemap.xml entry of {tried} is left on that host and allowed by robots.txt"
        )
    return pages


async def finish_dispatch(
    audit_id: uuid.UUID, *, status: str, error: str | None, worker_id: str | None
) -> None:
    """Close a dispatch row: its work was to queue page audits, so it has no report of its own."""
    async with session_scope() as session:
        await repo.finish_audit(
            session,
            audit_id=audit_id,
            status=status,
            pages_count=0,
            report_key=None,
            error=error,
            worker_id=worker_id,
        )
        await session.commit()


async def run_sitemap_audit(
    url: str,
    *,
    audit_id: uuid.UUID,
    pages_limit: int,
    settings: Settings,
    agents: Sequence[str] = (),
    ignore_robots: bool = False,
    worker_id: str | None = None,
    progress: ProgressFn | None = None,
    cancelled: CancelFn | None = None,
) -> list[uuid.UUID]:
    """Queue one page audit per sitemap entry and finish the dispatch row with the count.

    The row the worker claimed is not turned into a report: a merged report would count the same
    finding twice once the page rows land in the site ledger, and a batch that claims to be an
    audit of a page would have to invent one. `pages_count` says what was queued, and the page rows
    carry the findings.
    """
    limit = max(1, min(pages_limit, SITEMAP_MAX_PAGES))

    async def stop_if_cancelled() -> None:
        """A cancel is honoured at both boundaries: before discovery and before the queue."""
        if cancelled is not None and await cancelled():
            await finish_dispatch(
                audit_id,
                status=lifecycle.CANCELLED,
                error="cancelled by the operator",
                worker_id=worker_id,
            )
            raise AuditCancelled("cancelled by the operator")

    try:
        # The stage write is fenced: a row another worker has claimed raises LeaseLost here, and
        # the except below lets that through instead of finishing somebody else's run.
        if progress is not None:
            await progress("discover")
        await stop_if_cancelled()
        pages = await sitemap_pages(
            url,
            max_pages=limit,
            settings=settings,
            allowed_private_hosts=settings.allowed_private_host_set,
            ignore_robots=ignore_robots,
        )
        # Discovery can take a minute on a slow site; an operator who cancelled while it ran must
        # not get page audits queued behind a row that then claims to be completed.
        await stop_if_cancelled()
        async with session_scope() as session:
            queued = [
                await repo.create_audit(
                    session,
                    site_url=page,
                    agent_version=current_agent_version(settings),
                    config=audit_config(
                        settings, agents=agents, ignore_robots=ignore_robots, scope="page"
                    ),
                    status=lifecycle.QUEUED,
                    owner_id=settings.owner_id,
                    commit=False,
                )
                for page in pages
            ]
            finished = await repo.finish_audit(
                session,
                audit_id=audit_id,
                status=lifecycle.COMPLETED,
                pages_count=len(queued),
                report_key=None,
                worker_id=worker_id,
            )
            if not finished:
                await session.rollback()
                raise LeaseLost(f"{audit_id} was finished by another owner")
            await session.commit()
        return queued
    except (AuditCancelled, LeaseLost):
        raise
    except Exception as error:
        await finish_dispatch(
            audit_id, status=lifecycle.FAILED, error=str(error)[:2000], worker_id=worker_id
        )
        raise
