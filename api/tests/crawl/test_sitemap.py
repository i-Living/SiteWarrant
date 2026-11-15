import pytest

from app.crawl.sitemap import locs, reject_doctypes, sitemap_urls
from app.tools.http_get import HopCheck, LightResponse
from app.tools.robots import RobotsDisallowed

URLSET = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>http://example.com/a</loc></url>
  <url><loc> http://example.com/b </loc></url>
</urlset>"""

INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>http://example.com/sitemap-1.xml</loc></sitemap>
</sitemapindex>"""


def test_urlset_entries_are_read_and_trimmed() -> None:
    entries, is_index = locs(URLSET)
    assert entries == ["http://example.com/a", "http://example.com/b"]
    assert is_index is False


def test_sitemap_index_is_recognised() -> None:
    entries, is_index = locs(INDEX)
    assert entries == ["http://example.com/sitemap-1.xml"]
    assert is_index is True


def test_malformed_xml_yields_nothing() -> None:
    assert locs("<urlset><url>") == ([], False)


def test_entity_declarations_are_refused() -> None:
    """A sitemap comes from an untrusted host; entity expansion is how a small file grows."""
    hostile = '<!DOCTYPE urlset [<!ENTITY a "aaaa">]><urlset><url><loc>&a;</loc></url></urlset>'
    assert reject_doctypes(hostile) is True
    assert locs(hostile) == ([], False)


FOREIGN_CHILD_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://elsewhere.test/sitemap-1.xml</loc></sitemap>
</sitemapindex>"""


def response(url: str, text: str) -> LightResponse:
    return LightResponse(
        url=url,
        status_code=200,
        content_type="application/xml",
        redirects=[],
        headers={},
        text=text,
        truncated=False,
    )


async def test_an_index_child_on_another_host_is_not_fetched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery does not leave the audited host, and an index child is a fetch like any other."""
    requested: list[str] = []

    async def fake_get(
        url: str, *, hop_check: HopCheck | None = None, **_: object
    ) -> LightResponse:
        requested.append(url)
        return response(url, FOREIGN_CHILD_INDEX)

    monkeypatch.setattr("app.crawl.sitemap.http_get", fake_get)

    entries = await sitemap_urls(
        "https://example.test/page",
        user_agent="SiteWarrant/0.1",
        allowed_private_hosts=frozenset(),
        timeout_s=1.0,
    )

    assert entries == []
    assert requested == ["https://example.test/page/sitemap.xml"]


async def test_a_policy_refusal_leaves_the_run_without_a_sitemap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """robots.txt applies to /sitemap.xml too, and a refusal is not an exception for the caller."""
    consulted: list[str] = []

    async def refusing(url: str) -> None:
        consulted.append(url)
        raise RobotsDisallowed(f"robots.txt disallows {url}")

    async def fake_get(
        url: str, *, hop_check: HopCheck | None = None, **_: object
    ) -> LightResponse:
        if hop_check is not None:
            await hop_check(url)
        return response(url, URLSET)

    monkeypatch.setattr("app.crawl.sitemap.http_get", fake_get)

    entries = await sitemap_urls(
        "https://example.test/",
        user_agent="SiteWarrant/0.1",
        allowed_private_hosts=frozenset(),
        timeout_s=1.0,
        hop_check=refusing,
    )

    assert entries == []
    assert consulted == ["https://example.test/sitemap.xml"]
