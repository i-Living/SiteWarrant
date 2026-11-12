from collections.abc import Callable
from typing import Any

import pytest

from app.tools.http_get import (
    MAX_BODY_BYTES,
    HttpGetBlocked,
    HttpGetFailed,
    LightResponse,
    http_get,
    is_html,
)

ALLOW = frozenset({"127.0.0.1"})
Route = tuple[int, dict[str, str], bytes]
Builder = Callable[[str], dict[str, Route]]


def redirect_to_metadata(origin: str) -> dict[str, Route]:
    return {
        "/to-private": (302, {"Location": "http://169.254.169.254/latest/meta-data"}, b""),
    }


def redirect_inside(origin: str) -> dict[str, Route]:
    return {
        "/old": (302, {"Location": "/new"}, b""),
        "/new": (200, {}, b"<html><body>new</body></html>"),
    }


def loop(origin: str) -> dict[str, Route]:
    return {"/loop": (302, {"Location": "/loop"}, b"")}


def big(origin: str) -> dict[str, Route]:
    return {"/big": (200, {}, b"x" * 4096)}


def missing(origin: str) -> dict[str, Route]:
    return {}


def image(origin: str) -> dict[str, Route]:
    return {"/logo.png": (200, {"Content-Type": "image/png"}, b"\x89PNG")}


async def get(site: Any, path: str, *, max_bytes: int = MAX_BODY_BYTES) -> LightResponse:
    return await http_get(
        site.url(path),
        user_agent="test-agent",
        allowed_private_hosts=ALLOW,
        max_bytes=max_bytes,
    )


@pytest.mark.parametrize("site", [redirect_to_metadata], indirect=True)
async def test_redirect_to_a_private_address_is_refused(site) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(HttpGetBlocked):
        await get(site, "/to-private")


@pytest.mark.parametrize("site", [redirect_inside], indirect=True)
async def test_redirect_inside_the_host_is_followed(site) -> None:  # type: ignore[no-untyped-def]
    response = await get(site, "/old")
    assert response.status_code == 200
    assert response.url == site.url("/new")


@pytest.mark.parametrize("site", [loop], indirect=True)
async def test_redirect_loop_fails(site) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(HttpGetFailed):
        await get(site, "/loop")


@pytest.mark.parametrize("site", [big], indirect=True)
async def test_body_cap_marks_the_response_truncated(site) -> None:  # type: ignore[no-untyped-def]
    response = await get(site, "/big", max_bytes=1024)
    assert response.truncated is True
    assert len(response.text) <= 1024


@pytest.mark.parametrize("site", [missing], indirect=True)
async def test_error_status_is_returned(site) -> None:  # type: ignore[no-untyped-def]
    response = await get(site, "/nothing-here")
    assert response.status_code == 404


@pytest.mark.parametrize("site", [image], indirect=True)
async def test_content_type_is_reported(site) -> None:  # type: ignore[no-untyped-def]
    response = await get(site, "/logo.png")
    assert is_html(response.content_type) is False


def test_is_html_matches_a_charset_suffix() -> None:
    assert is_html("text/html; charset=utf-8") is True
    assert is_html("application/xhtml+xml") is True
    assert is_html("application/json") is False
