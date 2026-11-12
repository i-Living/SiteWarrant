from app.crawl.links import is_crawlable, parse_html

PAGE = "http://example.com/blog/post-1.html"


def test_relative_links_become_absolute() -> None:
    parsed = parse_html('<a href="../about.html">About</a>', PAGE)
    assert parsed.links == ["http://example.com/about.html"]


def test_fragments_are_stripped_and_duplicates_collapsed() -> None:
    html = '<a href="/a#one">A</a><a href="/a#two">A</a><a href="/a">A</a>'
    parsed = parse_html(html, PAGE)
    assert parsed.links == ["http://example.com/a"]


def test_non_page_schemes_and_assets_are_skipped() -> None:
    html = (
        '<a href="mailto:hi@example.com">mail</a>'
        '<a href="javascript:void(0)">js</a>'
        '<a href="/logo.png">png</a>'
        '<a href="/doc.pdf">pdf</a>'
        '<a href="/feed.xml">xml</a>'
        '<a href="/real">real</a>'
    )
    assert parse_html(html, PAGE).links == ["http://example.com/real"]


def test_base_href_is_applied() -> None:
    html = '<head><base href="http://example.com/blog/"></head><a href="post-2.html">next</a>'
    assert parse_html(html, PAGE).links == ["http://example.com/blog/post-2.html"]


def test_meta_robots_nofollow_is_reported() -> None:
    html = '<head><meta name="robots" content="noindex, nofollow"></head><a href="/a">a</a>'
    parsed = parse_html(html, PAGE)
    assert parsed.nofollow is True
    assert parsed.links == ["http://example.com/a"]


def test_rel_nofollow_on_a_single_link_is_reported() -> None:
    html = '<a rel="nofollow" href="/a">a</a>'
    assert parse_html(html, PAGE).nofollow is True


def test_canonical_is_reported() -> None:
    html = '<head><link rel="canonical" href="/blog/post-1.html"></head>'
    assert parse_html(html, PAGE).canonical == PAGE


def test_empty_shell_has_no_text() -> None:
    """This is what sends the crawler to the browser."""
    parsed = parse_html('<body><div id="root"></div><script>void 0</script></body>', PAGE)
    assert parsed.has_text is False
    assert parsed.links == []


def test_body_text_is_detected() -> None:
    assert parse_html("<body><p>Hello</p></body>", PAGE).has_text is True


def test_title_text_does_not_count_as_body_text() -> None:
    parsed = parse_html("<head><title>Only a title</title></head><body></body>", PAGE)
    assert parsed.has_text is False


def test_script_text_does_not_count_as_body_text() -> None:
    parsed = parse_html('<body><script>document.write("hi")</script></body>', PAGE)
    assert parsed.has_text is False


def test_only_http_and_https_are_crawlable() -> None:
    assert is_crawlable("http://example.com/a") is True
    assert is_crawlable("https://example.com/a") is True
    assert is_crawlable("ftp://example.com/a") is False
    assert is_crawlable("mailto:hi@example.com") is False
