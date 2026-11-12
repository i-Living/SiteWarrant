from urllib.parse import urlsplit

import httpx
from protego import Protego

from app.tools.guard import is_blocked

ROBOTS_TIMEOUT_S = 5.0


class RobotsDisallowed(RuntimeError):
    """robots.txt forbids this user agent from fetching the page."""


def robots_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/robots.txt"


def parse_robots(text: str) -> Protego:
    """Parse robots.txt with RFC 9309 semantics.

    The stdlib robotparser returns the first matching rule instead of the longest one, so
    a file that says "Allow: /" before "Disallow: /private" allows everything. That is a
    silent correctness bug inside a guard, hence the dedicated parser.
    """
    return Protego.parse(text)


async def fetch_robots(url: str, user_agent: str, *, allow_private: bool) -> Protego | None:
    """Return the parsed robots.txt, or None when the host publishes no rules.

    A missing file (any 4xx) means "no restrictions" per RFC 9309. Redirects are not
    followed: a robots.txt that points elsewhere is treated as absent.
    """
    target = robots_url(url)
    if is_blocked(target, allow_private=allow_private):
        return None
    try:
        async with httpx.AsyncClient(timeout=ROBOTS_TIMEOUT_S) as client:
            response = await client.get(target, headers={"User-Agent": user_agent})
    except httpx.HTTPError:
        return None
    if response.status_code >= 400:
        return None
    return parse_robots(response.text)


async def ensure_allowed(url: str, user_agent: str, *, allow_private: bool) -> None:
    parser = await fetch_robots(url, user_agent, allow_private=allow_private)
    if parser is None:
        return
    if not parser.can_fetch(url, user_agent):
        raise RobotsDisallowed(f"robots.txt disallows {url} for {user_agent}")
