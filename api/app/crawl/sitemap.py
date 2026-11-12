import xml.etree.ElementTree as ElementTree

from app.tools.http_get import HttpGetBlocked, HttpGetFailed, http_get

MAX_SITEMAP_URLS = 500
MAX_CHILD_SITEMAPS = 5


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
    start_url: str, *, user_agent: str, allowed_private_hosts: frozenset[str], timeout_s: float
) -> list[str]:
    """URLs published by /sitemap.xml, one level of a sitemap index deep.

    Every entry is returned as written; the caller re-validates the host and the robots
    policy, because a sitemap can list anything, including another host.
    """
    root = start_url.split("?", 1)[0].rstrip("/")
    found: list[str] = []
    try:
        response = await http_get(
            f"{root}/sitemap.xml",
            user_agent=user_agent,
            allowed_private_hosts=allowed_private_hosts,
            timeout_s=timeout_s,
        )
    except (HttpGetBlocked, HttpGetFailed):
        return []
    if response.status_code >= 400 or response.truncated:
        return []
    entries, is_index = locs(response.text)
    if not is_index:
        return entries
    for child in entries[:MAX_CHILD_SITEMAPS]:
        try:
            nested = await http_get(
                child,
                user_agent=user_agent,
                allowed_private_hosts=allowed_private_hosts,
                timeout_s=timeout_s,
            )
        except (HttpGetBlocked, HttpGetFailed):
            continue
        if nested.status_code >= 400 or nested.truncated:
            continue
        child_entries, _ = locs(nested.text)
        found.extend(child_entries)
    return found[:MAX_SITEMAP_URLS]
