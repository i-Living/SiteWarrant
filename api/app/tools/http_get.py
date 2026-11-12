from collections.abc import Awaitable, Callable

import httpx
from pydantic import BaseModel

from app.tools.guard import is_blocked, peer_address, peer_is_blocked

# Called for every hop before its request is sent: robots.txt applies to a redirect target
# too, and the caller is the only one that knows the policy.
HopCheck = Callable[[str], Awaitable[None]]

DEFAULT_TIMEOUT_S = 10.0
MAX_REDIRECTS = 5
MAX_BODY_BYTES = 2 * 1024 * 1024


class HttpGetBlocked(RuntimeError):
    """The guard refused a URL, usually a private address or a redirect to one."""


class HttpGetFailed(RuntimeError):
    """The request failed at the transport level or exceeded its deadline."""


class LightResponse(BaseModel):
    """A fetched document, already through the guard.

    `truncated` is load-bearing: a body cut at the cap has an incomplete link list, so the
    crawler must not treat its children as the full set.
    """

    url: str
    status_code: int
    content_type: str
    redirects: list[str]
    headers: dict[str, str]
    text: str
    truncated: bool


def is_html(content_type: str) -> bool:
    return "html" in content_type.lower()


async def http_get(
    url: str,
    *,
    user_agent: str,
    allowed_private_hosts: frozenset[str],
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_bytes: int = MAX_BODY_BYTES,
    hop_check: HopCheck | None = None,
) -> LightResponse:
    """Fetch a document with the SSRF guard on every hop and a hard body cap.

    Redirects are followed by hand rather than by httpx, because httpx would follow them
    without asking the guard. The peer address of each connection is checked too: the name
    is resolved for the guard and again by the transport, so a rebinding answer would
    otherwise land on a private address.
    """
    target = url
    chain: list[str] = []
    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            chain.append(target)
            if await is_blocked(target, allowed_private_hosts=allowed_private_hosts):
                raise HttpGetBlocked(f"{target} is not a public address")
            if hop_check is not None:
                await hop_check(target)
            try:
                async with client.stream("GET", target, headers={"User-Agent": user_agent}) as res:
                    host = httpx.URL(target).host or ""
                    if peer_is_blocked(peer_address(res), host, allowed_private_hosts):
                        raise HttpGetBlocked(f"connection to {target} landed on a private address")
                    if res.is_redirect:
                        location = res.headers.get("location")
                        if not location:
                            raise HttpGetFailed(f"redirect without a location at {target}")
                        target = str(httpx.URL(target).join(location))
                        continue
                    status_code = res.status_code
                    content_type = res.headers.get("content-type", "")
                    headers = {name.lower(): value for name, value in res.headers.items()}
                    chunks: list[bytes] = []
                    total = 0
                    truncated = False
                    async for chunk in res.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            truncated = True
                            break
                        chunks.append(chunk)
                    encoding = res.charset_encoding or "utf-8"
                    text = b"".join(chunks).decode(encoding, errors="replace")
            except httpx.HTTPError as error:
                raise HttpGetFailed(f"{target} is unreachable: {error}") from error
            return LightResponse(
                url=str(res.url),
                status_code=status_code,
                content_type=content_type,
                redirects=chain[:-1],
                headers=headers,
                text=text,
                truncated=truncated,
            )
    raise HttpGetFailed(f"{url} redirected more than {MAX_REDIRECTS} times")
