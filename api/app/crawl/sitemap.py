import xml.etree.ElementTree as ElementTree
from urllib.parse import urlsplit

from app.crawl.links import same_host
from app.tools.http_get import HopCheck, HttpGetBlocked, HttpGetFailed, http_get
from app.tools.robots import RobotsDisallowed, RobotsUnavailable

MAX_SITEMAP_URLS = 500
MAX_CHILD_SITEMAPS = 5

# A refusal by the policy, or an unreadable policy, means this run has no sitemap to read. It is
# not an error of the caller: the crawler still walks the start page and its links, and a sitemap
# dispatch fails with "no readable /sitemap.xml", which is what it has.
SITEMAP_REFUSED = (HttpGetBlocked, HttpGetFailed, RobotsDisallowed, RobotsUnavailable)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def reject_doctypes(text: str) -> bool:
    """Refuse a sitemap that declares entities.

    The body comes from an untrusted host, and stdlib ElementTree expands internal entities,
    which is how a small document becomes a large allocation. A real sitemap needs no
    doctype, so the declaration is rejected instead of parsed.
    """
    lowered = text.lower()
    return "<!doctype" in lowered or "<!entity" in lowered


def locs(text: str) -> tuple[list[str], bool]:
    """Return the loc entries and whether the document is a sitemap index."""
    if reject_doctypes(text):
        return [], False
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return [], False
    urls = [
        (element.text or "").strip()
        for element in root.iter()
        if local_name(element.tag) == "loc" and (element.text or "").strip()
    ]
    return urls[:MAX_SITEMAP_URLS], local_name(root.tag) == "sitemapindex"


async def sitemap_urls(
    start_url: str,
    *,
    user_agent: str,
    allowed_private_hosts: frozenset[str],
    timeout_s: float,
    hop_check: HopCheck | None = None,
) -> list[str]:
    """URLs published by /sitemap.xml, one level of a sitemap index deep.

    `hop_check` is the caller's policy for a fetched URL — `robots_hop_check` in the audit and in
    the crawler — and it is consulted for the sitemap itself as well as for each index child,
    because /sitemap.xml is a URL this tool fetches like any other. A policy that refuses, or a
    policy that cannot be read, leaves this run without a sitemap: the refusal is not a finding.

    An index child is only fetched when it stays on the audited host: discovery does not leave the
    host set, and a child is a fetch like any other. Every entry is returned as written; the
    caller re-validates the extension and applies the policy to the pages, because a sitemap can
    list anything, including another host.
    """
    root = start_url.split("?", 1)[0].rstrip("/")
    host = (urlsplit(start_url).hostname or "").lower()
    found: list[str] = []
    try:
        response = await http_get(
            f"{root}/sitemap.xml",
            user_agent=user_agent,
            allowed_private_hosts=allowed_private_hosts,
            timeout_s=timeout_s,
            hop_check=hop_check,
        )
    except SITEMAP_REFUSED:
        return []
    if response.status_code >= 400 or response.truncated:
        return []
    entries, is_index = locs(response.text)
    if not is_index:
        return entries
    for child in entries[:MAX_CHILD_SITEMAPS]:
        if not same_host(child, host):
            continue
        try:
            nested = await http_get(
                child,
                user_agent=user_agent,
                allowed_private_hosts=allowed_private_hosts,
                timeout_s=timeout_s,
                hop_check=hop_check,
            )
        except SITEMAP_REFUSED:
            continue
        if nested.status_code >= 400 or nested.truncated:
            continue
        child_entries, _ = locs(nested.text)
        found.extend(child_entries)
    return found[:MAX_SITEMAP_URLS]
