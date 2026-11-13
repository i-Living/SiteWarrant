"""A survey of the fixture: several pages, one report, per-page causes kept apart."""

import pytest

from app.core.config import get_settings
from app.crawl.crawler import CrawlFailed
from app.crawl.models import CrawlLimits
from app.survey import run_survey

pytestmark = pytest.mark.integration

URL = "http://localhost:8081/"


async def test_a_survey_merges_the_pages_the_crawl_selected() -> None:
    settings = get_settings()
    result = await run_survey(
        URL,
        limits=CrawlLimits(max_pages=4, max_depth=2, pages_per_template=1),
        settings=settings,
        allowed_private_hosts=frozenset({"localhost"}),
        allow_private=True,
    )
    report = result.report

    assert len(result.pages) >= 2, "the fixture has a journal and a product list to reach"
    assert report.summary.pages_audited == len(result.pages)
    assert result.failures == []
    assert report.status == "completed"
    assert report.summary.findings_total == len(report.findings) > 0
    assert report.summary.duration_ms > 0
    # Every finding names a page the crawl selected, and keeps the evidence its page proved.
    assert {finding.page_url for finding in report.findings} <= set(result.pages)
    assert all(finding.evidence for finding in report.findings)
    # A cause stays on one page: two pages that both carry a header are two causes, and a merged
    # cluster would claim one fix for blocks that are not the same block.
    by_id = {finding.id: finding for finding in report.findings}
    for cause in report.root_causes:
        assert len({by_id[finding_id].page_url for finding_id in cause.finding_ids}) == 1


async def test_a_survey_of_a_refused_start_page_fails_loudly() -> None:
    """A survey of nothing must not read like a clean site."""
    settings = get_settings()
    with pytest.raises(CrawlFailed, match="could not be crawled"):
        await run_survey(
            "http://localhost:8081/blocked.html",
            limits=CrawlLimits(max_pages=1, max_depth=0),
            settings=settings,
            allowed_private_hosts=frozenset({"localhost"}),
            allow_private=True,
        )
