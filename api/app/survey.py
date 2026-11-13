"""Audit the pages a crawl selected, and merge them into one report for the site.

One page audits itself; a site needs discovery first, because auditing the home page says nothing
about the fifty pages behind it. This module runs the existing per-page audit over the crawl's
selection and merges the results into one artifact, so a site has one `report.json` instead of
fifty (docs/PLAN.md, definition of done §16.1).

It deliberately does not re-cluster across pages. A root cause is a block on a page — two pages that
both carry a `header` do not share a cause, and merging them would invent one neither page has
(docs/PLAN.md section 6, invariant 3). The merged report therefore keeps the per-page causes as they
came, and `pages_audited` says how many pages they describe.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel, Field

from app.audit import run_audit
from app.core.config import Settings
from app.core.report import AgentSummaryOut, Report, build_report
from app.crawl.crawler import crawl as crawl_site
from app.crawl.models import CrawlLimits, CrawlReport

FAILURE_CHARS = 300


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
