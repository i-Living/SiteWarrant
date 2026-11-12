import pytest

from app.core.urls import page_key
from app.tools.guard import (
    clear_resolution_cache,
    is_blocked,
    is_private_address,
    pinning_argument,
)


def test_page_key_drops_scheme_query_fragment_and_trailing_slash() -> None:
    assert page_key("https://Example.com/a/b/?utm=1#top") == "example.com/a/b"


def test_page_key_of_root_is_host_only() -> None:
    assert page_key("http://localhost:8081/") == "localhost"


def test_private_address_ranges() -> None:
    assert is_private_address("127.0.0.1") is True
    assert is_private_address("10.1.2.3") is True
    assert is_private_address("192.168.1.10") is True
    assert is_private_address("169.254.169.254") is True
    assert is_private_address("::1") is True
    assert is_private_address("93.184.216.34") is False


async def test_loopback_is_blocked_without_an_allowlist() -> None:
    clear_resolution_cache()
    assert await is_blocked("http://127.0.0.1/", allowed_private_hosts=frozenset()) is True
    assert await is_blocked("http://localhost:8081/", allowed_private_hosts=frozenset()) is True


async def test_literal_private_address_is_blocked() -> None:
    empty = frozenset()
    assert (
        await is_blocked("http://169.254.169.254/latest/meta-data", allowed_private_hosts=empty)
        is True
    )
    assert await is_blocked("http://10.1.2.3/", allowed_private_hosts=empty) is True


async def test_allowlist_exempts_only_the_named_host() -> None:
    allowed = frozenset({"localhost"})
    assert await is_blocked("http://localhost:8081/", allowed_private_hosts=allowed) is False
    assert (
        await is_blocked("http://169.254.169.254/latest/meta-data", allowed_private_hosts=allowed)
        is True
    )


async def test_pinning_argument_skips_literal_addresses_and_localhost() -> None:
    assert await pinning_argument("http://localhost:8081/") == []
    assert await pinning_argument("http://93.184.216.34/") == []


@pytest.mark.parametrize("host", ["this-host-does-not-exist.invalid"])
async def test_unresolvable_host_is_not_treated_as_private(host: str) -> None:
    clear_resolution_cache()
    assert await is_blocked(f"http://{host}/", allowed_private_hosts=frozenset()) is False
