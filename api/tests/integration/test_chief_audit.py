"""The P4 acceptance: the fixture's banner is one cause, not a pile of unrelated findings."""

import uuid

import pytest
from sqlalchemy import select

from app.audit import run_audit
from app.core.db import session_scope
from app.core.models import Finding, RootCause

pytestmark = pytest.mark.integration

URL = "http://localhost:8081/"


async def test_the_banner_is_one_root_cause_with_symptoms_from_two_categories() -> None:
    report = await run_audit(URL, allow_private=True)

    assert report.summary.root_causes == 1
    cause = report.root_causes[0]
    assert cause.anchor == "header:nth-of-type(1)"
    assert cause.label == "header"
    assert len(cause.categories) >= 2, cause.categories
    assert len(cause.finding_ids) >= 2
    assert {"responsive", "a11y"} <= set(cause.categories)

    grouped = [finding for finding in report.findings if finding.root_cause_id == cause.id]
    assert {finding.rule_id for finding in grouped} == {"LAYOUT-OCCLUSION", "A11Y-LINK-NAME"}
    # The banner covers five links, and each covered target is its own finding: collapsing them
    # into one would hide four defects behind the first one's summary.
    covered = [finding for finding in grouped if finding.rule_id == "LAYOUT-OCCLUSION"]
    assert len(covered) == 5
    assert len({finding.subject for finding in covered}) == 5
    assert all(finding.priority > 0 for finding in report.findings)
    assert report.summary.duplicate_rate == 0.0


async def test_the_cluster_is_persisted_with_its_findings() -> None:
    report = await run_audit(URL, allow_private=True)

    async with session_scope() as session:
        causes = (
            (
                await session.execute(
                    select(RootCause).where(RootCause.audit_id == uuid.UUID(report.audit_id))
                )
            )
            .scalars()
            .all()
        )
        assert len(causes) == 1
        rows = (
            (await session.execute(select(Finding).where(Finding.root_cause_id == causes[0].id)))
            .scalars()
            .all()
        )
        assert len(rows) == len(report.root_causes[0].finding_ids)
        assert causes[0].anchor == "header:nth-of-type(1)"
        assert causes[0].priority > 0


async def test_a_page_level_defect_is_not_clustered() -> None:
    """An empty title is everywhere and therefore nowhere: no anchor, no cause."""
    report = await run_audit(URL, allow_private=True)
    titles = [finding for finding in report.findings if finding.rule_id == "SEO-TITLE"]
    assert titles
    assert titles[0].root_cause_id is None
