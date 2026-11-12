import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def artifacts_dir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Keep test artifacts out of the working tree."""
    path = tmp_path_factory.mktemp("artifacts")
    os.environ["ARTIFACTS_DIR"] = str(path)
    # Each test case gets its own event loop, so the engine must not pool connections.
    os.environ["SITEWARRANT_DB_NULL_POOL"] = "1"
    # Integration tests audit the fixture site on loopback. The HTTP API has no per-request
    # switch for this on purpose, so the permission comes from the deployment environment.
    os.environ["SITEWARRANT_ALLOW_PRIVATE_HOSTS"] = "1"
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


@pytest.fixture
def private_hosts_forbidden(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Turn the deployment-level permission off for one test."""
    from app.core.config import get_settings

    monkeypatch.setenv("SITEWARRANT_ALLOW_PRIVATE_HOSTS", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
