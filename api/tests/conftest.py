import os
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple

import pytest


@pytest.fixture(scope="session", autouse=True)
def artifacts_dir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Keep test artifacts out of the working tree."""
    path = tmp_path_factory.mktemp("artifacts")
    os.environ["ARTIFACTS_DIR"] = str(path)
    # Each test case gets its own event loop, so the engine must not pool connections.
    os.environ["SITEWARRANT_DB_NULL_POOL"] = "1"
    # Integration tests audit the fixture site on loopback. The HTTP API has no per-request
    # switch for this on purpose, so the permission comes from the deployment environment,
    # and it names the hosts: a redirect to a metadata address stays blocked.
    os.environ["SITEWARRANT_ALLOW_PRIVATE_HOSTS"] = "localhost,127.0.0.1"
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


@pytest.fixture
def private_hosts_forbidden(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Turn the deployment-level permission off for one test."""
    from app.core.config import get_settings

    monkeypatch.setenv("SITEWARRANT_ALLOW_PRIVATE_HOSTS", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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
