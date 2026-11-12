from app.tools.robots import peer_is_blocked


def test_public_peer_is_accepted() -> None:
    assert peer_is_blocked("93.184.216.34", "example.com", frozenset()) is False


def test_private_peer_is_refused() -> None:
    assert peer_is_blocked("10.0.0.5", "example.com", frozenset()) is True
    assert peer_is_blocked("169.254.169.254", "example.com", frozenset()) is True


def test_allowlisted_host_may_land_on_a_private_peer() -> None:
    assert peer_is_blocked("127.0.0.1", "localhost", frozenset({"localhost"})) is False


def test_unknown_peer_is_not_refused() -> None:
    assert peer_is_blocked(None, "example.com", frozenset()) is False
