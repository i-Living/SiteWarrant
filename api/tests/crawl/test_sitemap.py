from app.crawl.sitemap import locs, reject_doctypes

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
