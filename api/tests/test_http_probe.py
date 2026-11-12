import pytest

from app.tools.http_get import HttpGetBlocked
from app.tools.http_probe import SECURITY_HEADERS, HeaderFact, HttpFacts, probe


def facts(headers: list[HeaderFact]) -> HttpFacts:
    return HttpFacts(
        url="https://example.com/",
        status_code=200,
        content_type="text/html",
        redirects=[],
        headers=headers,
    )


def test_missing_headers_are_named() -> None:
    facts_ = facts([HeaderFact(name="x-frame-options", value="DENY")])
    missing = facts_.missing_security_headers()
    assert "x-frame-options" not in missing
    assert set(missing) == set(SECURITY_HEADERS) - {"x-frame-options"}


def test_header_lookup_is_exact() -> None:
    facts_ = facts([HeaderFact(name="strict-transport-security", value="max-age=31536000")])
    assert facts_.header("strict-transport-security") == "max-age=31536000"
    assert facts_.header("content-security-policy") is None


def secured(origin: str) -> dict[str, tuple[int, dict[str, str], bytes]]:
    return {
        "/": (
            200,
            {
                "Content-Type": "text/html; charset=utf-8",
                "Strict-Transport-Security": "max-age=63072000",
                "X-Content-Type-Options": "nosniff",
            },
            b"<html><body>ok</body></html>",
        )
    }


@pytest.mark.parametrize("site", [secured], indirect=True)
async def test_probe_records_present_headers_and_the_missing_ones(site) -> None:  # type: ignore[no-untyped-def]
    result = await probe(
        site.url("/"),
        user_agent="test-agent",
        allowed_private_hosts=frozenset({"127.0.0.1"}),
        timeout_s=5.0,
    )
    assert result.status_code == 200
    assert result.header("strict-transport-security") == "max-age=63072000"
    assert "content-security-policy" in result.missing_security_headers()


@pytest.mark.parametrize("site", [secured], indirect=True)
async def test_probe_refuses_a_host_outside_the_allowlist(site) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(HttpGetBlocked):
        await probe(
            site.url("/"),
            user_agent="test-agent",
            allowed_private_hosts=frozenset(),
            timeout_s=5.0,
        )
