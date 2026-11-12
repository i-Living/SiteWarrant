import pytest

from app.crawl.templates import template_pattern


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://example.com/", "/"),
        ("http://example.com", "/"),
        ("http://example.com/index.html", "/"),
        ("http://example.com/blog/", "/blog"),
        ("http://example.com/blog/index.html", "/blog"),
        ("http://example.com/about.html", "/about.html"),
        ("http://example.com/blog/post-1.html", "/blog/post-*.html"),
        ("http://example.com/products/item-24.html", "/products/item-*.html"),
        ("http://example.com/a/1.html", "/a/*.html"),
        ("http://example.com/blog/42", "/blog/*"),
        ("http://example.com/blog/2024/09/entry", "/blog/*/*/entry"),
        ("http://example.com/a/0123456789abcdef/", "/a/*"),
        ("http://example.com/a/9f1c0f5e-2b7a-4a61-9d5f-1d2c3b4a5e6f/x", "/a/*/x"),
    ],
)
def test_template_pattern(url: str, expected: str) -> None:
    assert template_pattern(url) == expected


def test_two_posts_share_a_template() -> None:
    first = template_pattern("http://example.com/blog/post-1.html")
    second = template_pattern("http://example.com/blog/post-2.html")
    assert first == second


def test_query_and_fragment_do_not_change_the_template() -> None:
    plain = template_pattern("http://example.com/blog/post-1.html")
    noisy = template_pattern("http://example.com/blog/post-1.html?utm_source=feed#top")
    assert plain == noisy


def test_words_are_kept() -> None:
    """A cluster key that erases words is useless in a report."""
    assert template_pattern("http://example.com/pricing/enterprise") == "/pricing/enterprise"
