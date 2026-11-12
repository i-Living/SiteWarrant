import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import NamedTuple

import pytest

Route = tuple[int, dict[str, str], bytes]
SiteBuilder = Callable[[str], dict[str, Route]]


class Site(NamedTuple):
    origin: str
    routes: dict[str, Route]

    def url(self, path: str) -> str:
        return f"{self.origin}{path}"


@pytest.fixture
def site(request: pytest.FixtureRequest) -> Iterator[Site]:
    """Serve an in-memory site on 127.0.0.1, so crawler tests never touch a real host."""
    builder: SiteBuilder = request.param
    holder: dict[str, dict[str, Route]] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            default: Route = (404, {"Content-Type": "text/plain"}, b"not found")
            status, headers, body = holder["routes"].get(self.path, default)
            self.send_response(status)
            for key, value in {"Content-Type": "text/html; charset=utf-8", **headers}.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    origin = f"http://127.0.0.1:{server.server_port}"
    holder["routes"] = builder(origin)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Site(origin=origin, routes=holder["routes"])
    finally:
        server.shutdown()
        thread.join(timeout=5)
