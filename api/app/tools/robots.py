from urllib.parse import urljoin, urlsplit

import httpx
from protego import Protego

from app.tools.guard import is_blocked

ROBOTS_TIMEOUT_S = 5.0
MAX_ROBOTS_REDIRECTS = 3


class RobotsDisallowed(RuntimeError):
    """robots.txt forbids this user agent from fetching the page."""


class RobotsUnavailable(RuntimeError):
    """robots.txt could not be read, so the policy is unknown and access is refused."""


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


async def fetch_robots(
    url: str, user_agent: str, *, allowed_private_hosts: frozenset[str]
) -> Protego | None:
    """Return the parsed robots.txt, or None when the host publishes no rules.

    RFC 9309 separates the cases: a 4xx answer means "no restrictions", a 5xx answer or a
    network failure means "policy unknown" and the crawler must refuse. Redirects are
    followed up to a small bound, with the guard re-run on every hop, because the rules
    reached through a redirect are the rules that apply.
    """
    target = robots_url(url)
    async with httpx.AsyncClient(timeout=ROBOTS_TIMEOUT_S, follow_redirects=False) as client:
        for _hop in range(MAX_ROBOTS_REDIRECTS + 1):
            if await is_blocked(target, allowed_private_hosts=allowed_private_hosts):
                raise RobotsUnavailable(f"robots.txt location {target} is not a public address")
            try:
                response = await client.get(target, headers={"User-Agent": user_agent})
            except httpx.HTTPError as error:
                raise RobotsUnavailable(f"robots.txt unreachable at {target}: {error}") from error
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise RobotsUnavailable(f"robots.txt redirect without a location at {target}")
                target = urljoin(target, location)
                continue
            if response.status_code >= 500:
                raise RobotsUnavailable(
                    f"robots.txt answered HTTP {response.status_code} at {target}"
                )
            if response.status_code >= 400:
                return None
            return parse_robots(response.text)
    raise RobotsUnavailable(f"robots.txt redirected more than {MAX_ROBOTS_REDIRECTS} times")


async def ensure_allowed(
    url: str, user_agent: str, *, allowed_private_hosts: frozenset[str]
) -> None:
    parser = await fetch_robots(url, user_agent, allowed_private_hosts=allowed_private_hosts)
    if parser is None:
        return
    if not parser.can_fetch(url, user_agent):
        raise RobotsDisallowed(f"robots.txt disallows {url} for {user_agent}")
