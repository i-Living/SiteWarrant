import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli import cli

pytestmark = pytest.mark.integration

FIXTURE = "http://localhost:8081"


def test_crawl_of_the_fixture_site_covers_every_template(tmp_path: Path) -> None:
    out = tmp_path / "pages.json"
    result = CliRunner().invoke(cli, ["crawl", f"{FIXTURE}/", "--allow-private", "--out", str(out)])
    assert result.exit_code == 0, result.output

    report = json.loads(out.read_text(encoding="utf-8"))
    coverage = {item["template"]: item for item in report["templates"]}

    # Three posts, two of them worth auditing.
    assert coverage["/blog/post-*.html"]["discovered"] == 3
    assert coverage["/blog/post-*.html"]["selected"] == 2
    assert coverage["/products/item-*.html"]["selected"] == 2
    # No template may exceed the per-template cap.
    assert all(
        item["selected"] <= report["limits"]["pages_per_template"] for item in coverage.values()
    )
    assert report["pages_selected"] == sum(item["selected"] for item in coverage.values())


def test_crawl_respects_robots_and_the_host_set(tmp_path: Path) -> None:
    out = tmp_path / "pages.json"
    CliRunner().invoke(cli, ["crawl", f"{FIXTURE}/", "--allow-private", "--out", str(out)])
    report = json.loads(out.read_text(encoding="utf-8"))
    by_url = {page["url"]: page for page in report["pages"]}

    assert by_url[f"{FIXTURE}/blocked.html"]["skip_reason"] == "robots"
    assert all("elsewhere.example" not in page["url"] for page in report["pages"])


def test_crawl_renders_an_app_shell(tmp_path: Path) -> None:
    out = tmp_path / "pages.json"
    CliRunner().invoke(cli, ["crawl", f"{FIXTURE}/", "--allow-private", "--out", str(out)])
    report = json.loads(out.read_text(encoding="utf-8"))
    shell = next(page for page in report["pages"] if page["url"].endswith("/spa.html"))
    assert shell["rendered"] is True


def test_crawl_requires_the_private_permission(
    tmp_path: Path, private_hosts_forbidden: None
) -> None:
    out = tmp_path / "pages.json"
    result = CliRunner().invoke(cli, ["crawl", f"{FIXTURE}/", "--out", str(out)])
    assert result.exit_code == 2
    # robots.txt is consulted before the first request, so the refusal can come from
    # either the robots policy or the request guard. Both are a failed crawl, not a report.
    assert "crawl failed" in result.output
    assert not out.exists()
