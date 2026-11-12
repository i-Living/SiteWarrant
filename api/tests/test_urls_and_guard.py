from app.core.urls import page_key
from app.tools.guard import is_blocked, resolves_to_private


def test_page_key_drops_scheme_query_fragment_and_trailing_slash() -> None:
    assert page_key("https://Example.com/a/b/?utm=1#top") == "example.com/a/b"


def test_page_key_of_root_is_host_only() -> None:
    assert page_key("http://localhost:8081/") == "localhost"


def test_loopback_is_blocked_by_default() -> None:
    assert is_blocked("http://127.0.0.1/", allow_private=False) is True
    assert is_blocked("http://localhost:8081/", allow_private=False) is True
    assert is_blocked("http://[::1]/", allow_private=False) is True


def test_private_and_link_local_ranges_are_blocked() -> None:
    assert is_blocked("http://10.1.2.3/", allow_private=False) is True
    assert is_blocked("http://192.168.1.10/", allow_private=False) is True
    assert is_blocked("http://169.254.169.254/latest/meta-data", allow_private=False) is True


def test_allow_private_lets_the_fixture_through() -> None:
    assert is_blocked("http://localhost:8081/", allow_private=True) is False


def test_public_literal_address_is_not_blocked() -> None:
    assert resolves_to_private("93.184.216.34") is False


def test_unresolvable_host_is_not_treated_as_private() -> None:
    assert resolves_to_private("this-host-does-not-exist.invalid") is False
