from app.tools.robots import parse_robots, robots_url

USER_AGENT = "SiteWarrant/0.1"


def test_robots_url_uses_the_origin() -> None:
    assert robots_url("https://example.com/a/b?x=1") == "https://example.com/robots.txt"
    assert robots_url("http://localhost:8081/blocked.html") == "http://localhost:8081/robots.txt"


def test_longest_match_wins_over_first_match() -> None:
    """The stdlib robotparser would return True here; this guard must not."""
    parser = parse_robots("User-agent: *\nAllow: /\nDisallow: /blocked.html\n")
    assert parser.can_fetch("https://example.com/", USER_AGENT) is True
    assert parser.can_fetch("https://example.com/blocked.html", USER_AGENT) is False


def test_parse_robots_blocks_a_whole_site() -> None:
    parser = parse_robots("User-agent: *\nDisallow: /\n")
    assert parser.can_fetch("https://example.com/anything", USER_AGENT) is False


def test_parse_robots_without_rules_allows_everything() -> None:
    parser = parse_robots("")
    assert parser.can_fetch("https://example.com/anything", USER_AGENT) is True
