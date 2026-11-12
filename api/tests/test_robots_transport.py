import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.tools.robots import (
    RobotsDisallowed,
    RobotsUnavailable,
    ensure_allowed,
    fetch_robots,
)

USER_AGENT = "SiteWarrant/0.1"
ALLOW_PRIVATE = frozenset({"127.0.0.1"})

Route = tuple[int, dict[str, str], bytes]


@pytest.fixture
def origin(request: pytest.FixtureRequest) -> Iterator[str]:
    routes: dict[str, Route] = request.param

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            return

        def do_GET(self) -> None:
            status, headers, body = routes.get(self.path, (404, {}, b""))
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.parametrize("origin", [{"/robots.txt": (404, {}, b"")}], indirect=True)
async def test_missing_robots_allows_everything(origin: str) -> None:
    assert (
        await fetch_robots(f"{origin}/page", USER_AGENT, allowed_private_hosts=ALLOW_PRIVATE)
        is None
    )
    await ensure_allowed(f"{origin}/page", USER_AGENT, allowed_private_hosts=ALLOW_PRIVATE)


@pytest.mark.parametrize(
    "origin", [{"/robots.txt": (200, {}, b"User-agent: *\nDisallow: /\n")}], indirect=True
)
async def test_disallow_all_blocks_the_page(origin: str) -> None:
    with pytest.raises(RobotsDisallowed):
        await ensure_allowed(f"{origin}/page", USER_AGENT, allowed_private_hosts=ALLOW_PRIVATE)


@pytest.mark.parametrize("origin", [{"/robots.txt": (503, {}, b"")}], indirect=True)
async def test_server_error_fails_closed(origin: str) -> None:
    with pytest.raises(RobotsUnavailable):
        await ensure_allowed(f"{origin}/page", USER_AGENT, allowed_private_hosts=ALLOW_PRIVATE)


@pytest.mark.parametrize(
    "origin",
    [
        {
            "/robots.txt": (302, {"Location": "/rules.txt"}, b""),
            "/rules.txt": (200, {}, b"User-agent: *\nDisallow: /\n"),
        }
    ],
    indirect=True,
)
async def test_robots_redirect_rules_are_applied(origin: str) -> None:
    with pytest.raises(RobotsDisallowed):
        await ensure_allowed(f"{origin}/page", USER_AGENT, allowed_private_hosts=ALLOW_PRIVATE)


@pytest.mark.parametrize(
    "origin",
    [
        {
            "/robots.txt": (302, {"Location": "/a.txt"}, b""),
            "/a.txt": (302, {"Location": "/b.txt"}, b""),
            "/b.txt": (302, {"Location": "/c.txt"}, b""),
            "/c.txt": (302, {"Location": "/d.txt"}, b""),
            "/d.txt": (200, {}, b"User-agent: *\nDisallow: /\n"),
        }
    ],
    indirect=True,
)
async def test_redirect_chain_is_bounded(origin: str) -> None:
    with pytest.raises(RobotsUnavailable):
        await fetch_robots(f"{origin}/page", USER_AGENT, allowed_private_hosts=ALLOW_PRIVATE)
