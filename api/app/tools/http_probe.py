from collections.abc import Awaitable, Callable

from pydantic import BaseModel

from app.tools.http_get import http_get

# Passive checks only: what the server says about itself. Nothing here sends a payload.
SECURITY_HEADERS: tuple[str, ...] = (
    "strict-transport-security",
    "content-security-policy",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
    "permissions-policy",
)
HEADER_BYTES = 64 * 1024


class HeaderFact(BaseModel):
    name: str
    value: str


class HttpFacts(BaseModel):
    """What the HTTP response says, independent of any viewport.

    Redirect hops are recorded because they are part of the answer a user gets: a 302 chain
    is a fact about the URL, not about the rendering.
    """

    url: str
    status_code: int
    content_type: str
    redirects: list[str]
    headers: list[HeaderFact]

    def header(self, name: str) -> str | None:
        for fact in self.headers:
            if fact.name == name:
                return fact.value
        return None

    def missing_security_headers(self) -> list[str]:
        present = {fact.name for fact in self.headers}
        return [name for name in SECURITY_HEADERS if name not in present]


async def probe(
    url: str,
    *,
    user_agent: str,
    allowed_private_hosts: frozenset[str],
    timeout_s: float,
    hop_check: Callable[[str], Awaitable[None]] | None = None,
) -> HttpFacts:
    response = await http_get(
        url,
        user_agent=user_agent,
        allowed_private_hosts=allowed_private_hosts,
        timeout_s=timeout_s,
        max_bytes=HEADER_BYTES,
        hop_check=hop_check,
    )
    return HttpFacts(
        url=response.url,
        status_code=response.status_code,
        content_type=response.content_type,
        redirects=response.redirects,
        headers=[
            HeaderFact(name=name, value=value)
            for name in SECURITY_HEADERS
            if (value := response.headers.get(name)) is not None
        ],
    )
