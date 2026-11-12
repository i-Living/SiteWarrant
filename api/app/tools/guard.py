import asyncio
import ipaddress
from typing import Any
from urllib.parse import urlsplit

import httpx
from playwright.async_api import CDPSession, Page

BLOCKED_SCHEMES = ("data:", "blob:", "about:", "chrome:")
LOCAL_HOSTNAMES = frozenset({"localhost", "localhost.localdomain"})

_resolution_cache: dict[str, list[str]] = {}


def clear_resolution_cache() -> None:
    _resolution_cache.clear()


async def resolve_host(host: str) -> list[str]:
    """Resolve a hostname without blocking the event loop."""
    if host in _resolution_cache:
        return _resolution_cache[host]
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None)
    except OSError:
        _resolution_cache[host] = []
        return []
    addresses = sorted({str(info[4][0]) for info in infos})
    _resolution_cache[host] = addresses
    return addresses


def is_private_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return True
    return (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    )


async def is_blocked(url: str, *, allowed_private_hosts: frozenset[str]) -> bool:
    """True when the URL must not be requested.

    A host on the allowlist is exempt, so the local fixture can be audited without also
    permitting a redirect to a metadata address. Unresolvable hosts are not blocked here:
    the browser fails on its own and the capture reports that failure. A name that does
    not resolve cannot reach a private address.
    """
    host = urlsplit(url).hostname
    if host is None:
        return True
    if host.lower() in allowed_private_hosts:
        return False
    if host in LOCAL_HOSTNAMES:
        return True
    addresses = await resolve_host(host)
    return any(is_private_address(address) for address in addresses)


def peer_address(response: httpx.Response) -> str | None:
    """Peer of the finished connection, as httpx reports it."""
    stream = response.extensions.get("network_stream")
    if stream is None:
        return None
    server = stream.get_extra_info("server_addr")
    if not server:
        return None
    return str(server[0])


def peer_is_blocked(peer: str | None, host: str, allowed_private_hosts: frozenset[str]) -> bool:
    """Detect a connection that landed on a private address the pre-check did not see.

    The name is resolved once for the guard and again by the transport, so a DNS answer
    that changes in between (rebinding) reaches a private address. httpx exposes the peer
    of the finished connection, which turns that into a refusal instead of a silently
    accepted response. Only the allowlisted hosts are exempt.
    """
    if peer is None or host.lower() in allowed_private_hosts:
        return False
    return is_private_address(peer)


async def pinning_argument(url: str) -> list[str]:
    """Chromium argument that pins a host to the address we validated.

    Without it the browser resolves the name again at connection time, so a DNS answer
    that changes between the check and the request (DNS rebinding) reaches an address the
    guard never saw. The crawl keeps to one host, so on that path the pinned set is the
    audited host. Third-party subresources are still resolved by the browser and are
    covered only by the per-request guard check, so do not describe the window as closed.
    """
    host = urlsplit(url).hostname
    if not host or host in LOCAL_HOSTNAMES:
        return []
    try:
        ipaddress.ip_address(host)
        return []
    except ValueError:
        pass
    addresses = await resolve_host(host)
    if not addresses:
        return []
    return [f"--host-resolver-rules=MAP {host} {addresses[0]}"]


async def install_request_guard(
    page: Page, *, allowed_private_hosts: frozenset[str]
) -> tuple[CDPSession, list[str]]:
    """Validate every request the page makes, including each redirect hop.

    Playwright's own route handler sees only the original request: the browser follows a
    redirect without calling it again, so a public URL can reach a private address
    unchecked. CDP's Fetch domain pauses every request, redirect targets included, and
    the decision is made per hop. Pinned by tests/integration/test_guard_redirects.py.
    """
    blocked: list[str] = []
    session = await page.context.new_cdp_session(page)
    await session.send("Fetch.enable", {"patterns": [{"urlPattern": "*"}]})
    tasks: set[asyncio.Task[None]] = set()

    async def decide(event: dict[str, Any]) -> None:
        request_id = event["requestId"]
        url = str(event["request"]["url"])
        try:
            if url.startswith(BLOCKED_SCHEMES):
                await session.send("Fetch.continueRequest", {"requestId": request_id})
                return
            if await is_blocked(url, allowed_private_hosts=allowed_private_hosts):
                blocked.append(url)
                await session.send(
                    "Fetch.failRequest",
                    {"requestId": request_id, "errorReason": "BlockedByClient"},
                )
                return
            await session.send("Fetch.continueRequest", {"requestId": request_id})
        except Exception:
            return

    def on_paused(event: dict[str, Any]) -> None:
        task = asyncio.create_task(decide(event))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    session.on("Fetch.requestPaused", on_paused)
    return session, blocked
