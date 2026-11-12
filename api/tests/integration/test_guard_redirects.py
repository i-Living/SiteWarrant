import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli import cli
from app.core.config import get_settings
from app.tools.fetch import BlockedRequestError, capture_page

pytestmark = pytest.mark.integration

FIXTURE = "http://localhost:8081/"


def test_redirect_to_a_metadata_address_is_blocked(tmp_path: Path) -> None:
    """The fixture page redirects to 169.254.169.254; the guard must refuse that hop.

    The fixture host itself is on the private allowlist, so this only passes if the guard
    validates each redirect target instead of the original URL alone.
    """
    out = tmp_path / "redirect.json"
    result = CliRunner().invoke(cli, ["audit", f"{FIXTURE}to-private", "--out", str(out)])
    assert result.exit_code == 2, result.output
    # The HTTP probe runs before the browser, so the hop is refused there first. The
    # browser guard is pinned separately below, because it must refuse the hop on its own.
    assert "169.254.169.254" in result.output
    assert not out.exists()


async def test_the_browser_guard_refuses_the_redirect_hop() -> None:
    """Without this, a probe failure could hide a broken browser guard."""
    with pytest.raises(BlockedRequestError):
        await capture_page(
            f"{FIXTURE}/to-private",
            get_settings(),
            allowed_private_hosts=frozenset({"localhost"}),
        )


def test_csp_page_is_still_audited(tmp_path: Path) -> None:
    """A strict script-src policy must not stop axe from running."""
    out = tmp_path / "csp.json"
    result = CliRunner().invoke(
        cli, ["audit", f"{FIXTURE}csp.html", "--allow-private", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    report = json.loads(out.read_text(encoding="utf-8"))
    assert [finding["rule_id"] for finding in report["findings"]] == ["A11Y-IMG-ALT"]
