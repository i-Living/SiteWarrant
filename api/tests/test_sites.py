"""The site views are only as good as the page identity they group by."""

import uuid
from datetime import UTC, datetime, timedelta

from app.api.main import page_summaries, site_host, site_path, url_rows
from app.core.models import Audit


def audit(url: str, *, minutes: int = 0, status: str = "completed") -> Audit:
    started = datetime(2026, 11, 13, 12, 0, tzinfo=UTC) + timedelta(minutes=minutes)
    return Audit(
        id=uuid.uuid4(),
        site_url=url,
        status=status,
        agent_version="v",
        config={},
        pages_count=1,
        report_key=None,
        started_at=started,
        finished_at=None if status == "running" else started,
    )


def test_site_host_keeps_a_non_default_port_and_drops_the_default() -> None:
    assert site_host("http://localhost:8081/x") == "localhost:8081"
    assert site_host("https://docs.python.org:443/3/") == "docs.python.org"
    assert site_host("http://Example.COM:80/") == "example.com"


def test_site_host_keeps_subdomains_and_www_apart() -> None:
    assert site_host("https://docs.example.com/") == "docs.example.com"
    assert site_host("https://www.example.com/") == "www.example.com"


def test_site_path_ignores_the_trailing_slash_and_the_query() -> None:
    assert site_path("https://example.com/") == "/"
    assert site_path("https://example.com/3/") == "/3"
    assert site_path("https://example.com/3?page=2#top") == "/3"


def test_one_page_merges_its_url_variants_and_sums_runs() -> None:
    newer = audit("https://example.com/3", minutes=5)
    older = audit("https://example.com/3/", minutes=1)
    rows = url_rows(
        [newer, older],
        [("https://example.com/3", 2), ("https://example.com/3/", 1)],
    )

    pages = page_summaries(rows)

    assert len(pages) == 1
    assert pages[0].audit_id == str(newer.id)
    assert pages[0].page == "/3"
    assert pages[0].runs == 3


def test_in_flight_comes_from_the_newest_row() -> None:
    done = audit("https://example.com/3", status="completed")
    assert url_rows([done], [("https://example.com/3", 5)])[0][2] == 0
    live = audit("https://example.com/4", status="running")
    assert url_rows([live], [("https://example.com/4", 1)])[0][2] == 1


def test_a_url_without_a_host_is_still_shown() -> None:
    assert site_host("not a url") == "not a url"
    assert site_path("not a url") == "/"
