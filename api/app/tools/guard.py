import ipaddress
import socket
from functools import lru_cache
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Route

LOCAL_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "127.0.0.1", "::1"})


@lru_cache(maxsize=1024)
def resolves_to_private(host: str) -> bool:
    """True when any resolved address is not publicly routable.

    Unresolvable hosts return False: the browser fails on its own and the error is
    reported as a capture failure, which is the honest outcome.
    """
    try:
        addresses = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in addresses:
        raw = info[4][0]
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            return True
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            return True
    return False


def is_blocked(url: str, *, allow_private: bool) -> bool:
    if allow_private:
        return False
    host = urlparse(url).hostname
    if host is None:
        return True
    if host in LOCAL_HOSTNAMES:
        return True
    return resolves_to_private(host)


async def install_request_guard(context: BrowserContext, *, allow_private: bool) -> list[str]:
    """Block every request that leaves for a private address.

    The guard runs on each request, so redirect hops and subresources are validated too,
    not only the URL the user typed.
    """
    blocked: list[str] = []

    async def handle(route: Route) -> None:
        url = route.request.url
        if url.startswith(("data:", "blob:", "about:")):
            await route.continue_()
            return
        if is_blocked(url, allow_private=allow_private):
            blocked.append(url)
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    await context.route("**/*", handle)
    return blocked
