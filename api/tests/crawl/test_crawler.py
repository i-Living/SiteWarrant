from collections.abc import Callable

import pytest

from app.core.config import get_settings
from app.crawl.crawler import CrawlFailed, crawl, normalize_url, same_host
from app.crawl.models import CrawlLimits

ALLOW = frozenset({"127.0.0.1"})
Route = tuple[int, dict[str, str], bytes]
Builder = Callable[[str], dict[str, Route]]

ROBOTS_ALLOW_ALL: Route = (
    200,
    {"Content-Type": "text/plain"},
    b"User-agent: *\nAllow: /\n",
)


def page(title: str, links: list[str], head: str = "") -> bytes:
    items = "".join(f'<li><a href="{link}">{link}</a></li>' for link in links)
    document = (
        f'<!doctype html><html lang="en"><head><title>{title}</title>{head}</head>'
        f"<body><h1>{title}</h1><ul>{items}</ul></body></html>"
    )
    return document.encode()


def limits(**overrides: object) -> CrawlLimits:
    base = {"max_pages": 50, "max_depth": 2, "pages_per_template": 2, "include_sitemap": False}
    return CrawlLimits(**{**base, **overrides})  # type: ignore[arg-type]


def three_templates(origin: str) -> dict[str, Route]:
    routes: dict[str, Route] = {"/robots.txt": ROBOTS_ALLOW_ALL}
    links = [f"/{prefix}/{index}.html" for prefix in ("a", "b", "c") for index in (1, 2, 3)]
    routes["/"] = (200, {}, page("home", links))
    for prefix in ("a", "b", "c"):
        for index in (1, 2, 3):
            routes[f"/{prefix}/{index}.html"] = (200, {}, page(f"{prefix}{index}", ["/"]))
    return routes


def external_links(origin: str) -> dict[str, Route]:
    return {
        "/robots.txt": ROBOTS_ALLOW_ALL,
        "/": (200, {}, page("home", ["http://other.example/x", "/local.html", "mailto:hi@x.test"])),
        "/local.html": (200, {}, page("local", [])),
    }


def robots_blocking(origin: str) -> dict[str, Route]:
    return {
        "/robots.txt": (
            200,
            {"Content-Type": "text/plain"},
            b"User-agent: *\nDisallow: /private.html\n",
        ),
        "/": (200, {}, page("home", ["/private.html", "/public.html"])),
        "/private.html": (200, {}, page("private", [])),
        "/public.html": (200, {}, page("public", [])),
    }


def chain(origin: str) -> dict[str, Route]:
    return {
        "/robots.txt": ROBOTS_ALLOW_ALL,
        "/": (200, {}, page("home", ["/one.html"])),
        "/one.html": (200, {}, page("one", ["/two.html"])),
        "/two.html": (200, {}, page("two", ["/three.html"])),
        "/three.html": (200, {}, page("three", [])),
    }


def nofollow(origin: str) -> dict[str, Route]:
    head = '<meta name="robots" content="nofollow">'
    return {
        "/robots.txt": ROBOTS_ALLOW_ALL,
        "/": (200, {}, page("home", ["/child.html"], head=head)),
        "/child.html": (200, {}, page("child", [])),
    }


def sitemap_site(origin: str) -> dict[str, Route]:
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{origin}/orphan.html</loc></url>"
        "<url><loc>http://elsewhere.example/page</loc></url>"
        "</urlset>"
    ).encode()
    return {
        "/robots.txt": ROBOTS_ALLOW_ALL,
        "/sitemap.xml": (200, {"Content-Type": "application/xml"}, sitemap),
        "/": (200, {}, page("home", [])),
        "/orphan.html": (200, {}, page("orphan", [])),
    }


def broken(origin: str) -> dict[str, Route]:
    return {
        "/robots.txt": ROBOTS_ALLOW_ALL,
        "/": (200, {}, page("home", ["/missing.html"])),
    }


def start_blocked(origin: str) -> dict[str, Route]:
    return {
        "/robots.txt": (200, {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow: /\n"),
        "/": (200, {}, page("home", [])),
    }


def shell(origin: str) -> dict[str, Route]:
    document = (
        b'<!doctype html><html lang="en"><head><title>shell</title></head>'
        b'<body><div id="root"></div><script>void 0</script></body></html>'
    )
    return {"/robots.txt": ROBOTS_ALLOW_ALL, "/": (200, {}, document)}


@pytest.mark.parametrize("site", [three_templates], indirect=True)
async def test_two_pages_per_template(site) -> None:  # type: ignore[no-untyped-def]
    report = await crawl(
        site.url("/"),
        limits=limits(),
        settings=get_settings(),
        allowed_private_hosts=ALLOW,
    )
    assert report.pages_discovered == 10
    assert report.pages_selected == 7
    coverage = {item.template: (item.discovered, item.selected) for item in report.templates}
    assert coverage == {
        "/": (1, 1),
        "/a/*.html": (3, 2),
        "/b/*.html": (3, 2),
        "/c/*.html": (3, 2),
    }
    assert report.skipped == {"template_limit": 3}


@pytest.mark.parametrize("site", [three_templates], indirect=True)
async def test_page_cap_stops_selection(site) -> None:  # type: ignore[no-untyped-def]
    report = await crawl(
        site.url("/"),
        limits=limits(max_pages=4, pages_per_template=5),
        settings=get_settings(),
        allowed_private_hosts=ALLOW,
    )
    assert report.pages_selected == 4
    assert report.skipped == {"page_limit": 6}


@pytest.mark.parametrize("site", [external_links], indirect=True)
async def test_discovery_stays_inside_the_host(site) -> None:  # type: ignore[no-untyped-def]
    report = await crawl(
        site.url("/"),
        limits=limits(),
        settings=get_settings(),
        allowed_private_hosts=ALLOW,
    )
    assert [page.url for page in report.pages] == [site.url("/"), site.url("/local.html")]


@pytest.mark.parametrize("site", [robots_blocking], indirect=True)
async def test_robots_is_checked_per_url(site) -> None:  # type: ignore[no-untyped-def]
    report = await crawl(
        site.url("/"),
        limits=limits(),
        settings=get_settings(),
        allowed_private_hosts=ALLOW,
    )
    reasons = {page.url: page.skip_reason for page in report.pages}
    assert reasons[site.url("/private.html")] == "robots"
    assert reasons[site.url("/public.html")] is None


@pytest.mark.parametrize("site", [robots_blocking], indirect=True)
async def test_ignore_robots_fetches_the_blocked_page(site) -> None:  # type: ignore[no-untyped-def]
    report = await crawl(
        site.url("/"),
        limits=limits(),
        settings=get_settings(),
        allowed_private_hosts=ALLOW,
        ignore_robots=True,
    )
    reasons = {page.url: page.skip_reason for page in report.pages}
    assert reasons[site.url("/private.html")] is None


@pytest.mark.parametrize("site", [chain], indirect=True)
async def test_depth_limit_stops_the_walk(site) -> None:  # type: ignore[no-untyped-def]
    report = await crawl(
        site.url("/"),
        limits=limits(max_depth=1),
        settings=get_settings(),
        allowed_private_hosts=ALLOW,
    )
    assert [page.url for page in report.pages] == [site.url("/"), site.url("/one.html")]


@pytest.mark.parametrize("site", [nofollow], indirect=True)
async def test_nofollow_page_contributes_no_children(site) -> None:  # type: ignore[no-untyped-def]
    report = await crawl(
        site.url("/"),
        limits=limits(),
        settings=get_settings(),
        allowed_private_hosts=ALLOW,
    )
    assert [page.url for page in report.pages] == [site.url("/")]


@pytest.mark.parametrize("site", [sitemap_site], indirect=True)
async def test_sitemap_seeds_discovery_and_is_host_filtered(site) -> None:  # type: ignore[no-untyped-def]
    report = await crawl(
        site.url("/"),
        limits=limits(include_sitemap=True),
        settings=get_settings(),
        allowed_private_hosts=ALLOW,
    )
    by_url = {page.url: page for page in report.pages}
    assert by_url[site.url("/orphan.html")].source == "sitemap"
    assert all("elsewhere.example" not in page.url for page in report.pages)


@pytest.mark.parametrize("site", [broken], indirect=True)
async def test_error_page_is_recorded_not_followed(site) -> None:  # type: ignore[no-untyped-def]
    report = await crawl(
        site.url("/"),
        limits=limits(),
        settings=get_settings(),
        allowed_private_hosts=ALLOW,
    )
    reasons = {page.url: page.skip_reason for page in report.pages}
    assert reasons[site.url("/missing.html")] == "http_404"


@pytest.mark.parametrize("site", [shell], indirect=True)
async def test_shell_without_render_is_recorded_as_a_page(site) -> None:  # type: ignore[no-untyped-def]
    report = await crawl(
        site.url("/"),
        limits=limits(),
        settings=get_settings(),
        allowed_private_hosts=ALLOW,
        render_empty_bodies=False,
    )
    assert report.pages_discovered == 1
    assert report.pages[0].rendered is False


def test_normalize_url_drops_the_fragment() -> None:
    assert normalize_url("http://example.com/a#top") == "http://example.com/a"


def test_same_host_is_case_insensitive() -> None:
    assert same_host("http://Example.com/a", "example.com") is True
    assert same_host("http://example.com.evil.test/a", "example.com") is False


@pytest.mark.parametrize("site", [start_blocked], indirect=True)
async def test_blocked_start_url_fails_the_crawl(site) -> None:  # type: ignore[no-untyped-def]
    """A crawl that cannot read its own start page must not report success."""
    with pytest.raises(CrawlFailed):
        await crawl(
            site.url("/"),
            limits=limits(),
            settings=get_settings(),
            allowed_private_hosts=ALLOW,
        )
