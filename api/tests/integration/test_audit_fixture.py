import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from app.audit import run_audit
from app.cli import cli
from app.core.db import session_scope
from app.core.models import Observation

pytestmark = pytest.mark.integration

EXPECTED = json.loads(
    (Path(__file__).parents[3] / "benchmark" / "fixtures" / "expected.json").read_text(
        encoding="utf-8"
    )
)


def test_fixture_reports_every_planted_defect(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    result = CliRunner().invoke(
        cli, ["audit", EXPECTED["url"], "--allow-private", "--out", str(out)]
    )
    assert result.exit_code == 1, result.output
    report = json.loads(out.read_text(encoding="utf-8"))

    assert sorted({finding["rule_id"] for finding in report["findings"]}) == EXPECTED["rule_ids"]
    # One defect per rule, except the banner: it covers five links, and each is its own finding.
    assert len(report["findings"]) == EXPECTED["findings_total"]
    assert report["summary"]["root_causes"] == EXPECTED["root_causes"]
    assert report["summary"]["duplicate_rate"] == 0.0
    blockers = sorted(
        finding["rule_id"] for finding in report["findings"] if finding["severity"] == "blocker"
    )
    assert blockers == EXPECTED["blockers"]
    assert report["summary"]["pages_audited"] == 1
    assert report["summary"]["by_severity"]["blocker"] == len(EXPECTED["blockers"])
    assert report["findings"][0]["page_key"] == EXPECTED["page_key"]


def test_every_finding_carries_resolvable_evidence(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    CliRunner().invoke(cli, ["audit", EXPECTED["url"], "--allow-private", "--out", str(out)])
    report = json.loads(out.read_text(encoding="utf-8"))

    for finding in report["findings"]:
        assert finding["evidence"], finding["rule_id"]
        for item in finding["evidence"]:
            uuid.UUID(item["observation_id"])


async def test_evidence_points_at_stored_observations() -> None:
    report = await run_audit(EXPECTED["url"], allow_private=True)
    cited = {
        uuid.UUID(item.observation_id) for finding in report.findings for item in finding.evidence
    }
    async with session_scope() as session:
        rows = await session.execute(select(Observation.id).where(Observation.id.in_(cited)))
        stored = set(rows.scalars())
    assert stored == cited


async def test_second_run_reports_the_same_rules() -> None:
    first = await run_audit(EXPECTED["url"], allow_private=True)
    second = await run_audit(EXPECTED["url"], allow_private=True)
    assert sorted(finding.rule_id for finding in first.findings) == sorted(
        finding.rule_id for finding in second.findings
    )


def test_private_address_without_flag_fails(tmp_path: Path, private_hosts_forbidden: None) -> None:
    out = tmp_path / "report.json"
    result = CliRunner().invoke(cli, ["audit", EXPECTED["url"], "--out", str(out)])
    assert result.exit_code == 2, result.output
    assert not out.exists()


def test_robots_disallow_stops_the_audit(tmp_path: Path) -> None:
    out = tmp_path / "blocked.json"
    blocked = f"{EXPECTED['url']}blocked.html"
    result = CliRunner().invoke(cli, ["audit", blocked, "--allow-private", "--out", str(out)])
    assert result.exit_code == 2, result.output
    assert "robots.txt disallows" in result.output
    assert not out.exists()


def test_ignore_robots_overrides_the_disallow(tmp_path: Path) -> None:
    out = tmp_path / "blocked.json"
    blocked = f"{EXPECTED['url']}blocked.html"
    result = CliRunner().invoke(
        cli, ["audit", blocked, "--allow-private", "--ignore-robots", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["summary"]["findings_total"] == 0
