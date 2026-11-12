from app.core.version import compute_agent_version

BASE = {
    "viewports": ("390x844", "768x1024", "1440x900"),
    "page_timeout_ms": 30_000,
    "capture_timeout_ms": 60_000,
    "user_agent": "SiteWarrant/0.1 (+https://github.com/i-Living/SiteWarrant)",
}


def test_version_is_stable_for_the_same_inputs() -> None:
    assert compute_agent_version(**BASE) == compute_agent_version(**BASE)


def test_user_agent_changes_the_version() -> None:
    other = {**BASE, "user_agent": "SomeOtherBot/1.0"}
    assert compute_agent_version(**BASE) != compute_agent_version(**other)


def test_capture_timeout_changes_the_version() -> None:
    other = {**BASE, "capture_timeout_ms": 5_000}
    assert compute_agent_version(**BASE) != compute_agent_version(**other)


def test_viewport_set_changes_the_version() -> None:
    other = {**BASE, "viewports": ("1440x900",)}
    assert compute_agent_version(**BASE) != compute_agent_version(**other)


def test_version_is_prefixed_with_the_hash_algorithm() -> None:
    version = compute_agent_version(**BASE)
    assert version.startswith("sha256:")
    assert len(version) == len("sha256:") + 16
