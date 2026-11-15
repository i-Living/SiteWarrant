"""Comparing two stored audits: what closed, what stayed, what is new, and when it is a lie."""

import uuid
from datetime import UTC, datetime

from app.compare import comparability, compare_reports
from app.core.report import (
    EvidenceOut,
    FindingOut,
    ImpactOut,
    Report,
    RootCauseOut,
    SummaryOut,
)


def finding(
    *,
    rule_id: str = "SEO-TITLE",
    severity: str = "major",
    page: str = "/",
    subject: str | None = None,
    cause: str | None = None,
) -> FindingOut:
    return FindingOut(
        id=str(uuid.uuid4()),
        rule_id=rule_id,
        category="seo",
        severity=severity,  # type: ignore[arg-type]
        title="t",
        summary="s",
        suggested_fix="f",
        impact=ImpactOut(conversion=0, seo=2, ux=0),
        confidence=1.0,
        agent="rules",
        subject=subject,
        page_url=f"http://localhost:8081{page}",
        page_key="localhost",
        root_cause_id=cause,
        evidence=[EvidenceOut(kind="dom", observation_id=str(uuid.uuid4()))],
    )


def cause(cause_id: str, *, anchor: str, findings: list[FindingOut]) -> RootCauseOut:
    return RootCauseOut(
        id=cause_id,
        kind="place",
        anchor=anchor,
        label=anchor.split(":")[0],
        categories=["seo", "a11y"],
        summary="s",
        rationale="r",
        severity="major",
        priority=1.0,
        finding_ids=[item.id for item in findings],
    )


def report(
    *,
    site: str = "http://localhost:8081/",
    version: str = "sha256:one",
    findings: list[FindingOut] | None = None,
    causes: list[RootCauseOut] | None = None,
) -> Report:
    items = findings or []
    return Report(
        audit_id=str(uuid.uuid4()),
        site=site,
        agent_version=version,
        status="completed",
        generated_at=datetime(2026, 11, 15, tzinfo=UTC),
        summary=SummaryOut(
            pages_audited=1,
            findings_total=len(items),
            by_severity={"blocker": 0, "major": len(items), "minor": 0, "info": 0},
            scores={},
            duration_ms=1,
            observations_by_tool={},
            root_causes=len(causes or []),
        ),
        findings=items,
        root_causes=causes or [],
    )


def test_a_closed_and_a_new_finding_are_reported_with_their_cause() -> None:
    header = "header:nth-of-type(1)"
    banner = finding(rule_id="SEO-TITLE", cause="cause-header")
    fresh = finding(rule_id="A11Y-LANG", page="/", cause="cause-about")
    before = report(
        findings=[banner],
        causes=[cause("cause-header", anchor=header, findings=[banner])],
    )
    after = report(
        findings=[fresh],
        causes=[cause("cause-about", anchor="main:nth-of-type(1)", findings=[fresh])],
    )
    result = compare_reports(before, after)
    assert result.comparable
    assert [item.rule_id for item in result.closed] == ["SEO-TITLE"]
    assert [item.rule_id for item in result.new] == ["A11Y-LANG"]
    assert result.remaining == []
    causes = {(item.anchor, item.page): item for item in result.causes}
    assert causes[(header, "/")].closed == 1
    assert causes[("main:nth-of-type(1)", "/")].new == 1


def test_a_finding_present_in_both_is_remaining() -> None:
    same = finding(rule_id="SEO-H1")
    before = report(findings=[same])
    after = report(findings=[same.model_copy()])
    result = compare_reports(before, after)
    assert len(result.remaining) == 1
    assert result.closed == [] and result.new == []


def test_two_sites_are_not_a_comparison_and_say_why() -> None:
    before = report(site="http://localhost:8081/")
    after = report(site="https://example.com/")
    reasons, _ = comparability(before, after)
    result = compare_reports(before, after)
    assert not result.comparable
    assert any("different sites" in reason for reason in reasons)


def test_a_shared_path_is_what_makes_two_reports_comparable() -> None:
    before = report(findings=[finding(page="/a")])
    after = report(findings=[finding(page="/b")])
    result = compare_reports(before, after)
    assert not result.comparable
    assert any("share no page path" in reason for reason in result.reasons)


def test_a_version_change_is_a_note_not_a_refusal() -> None:
    """Comparing across agent versions is the point of a prompt change — it must stay allowed."""
    before = report(version="sha256:old")
    after = report(version="sha256:new")
    reasons, notes = comparability(before, after)
    assert reasons == []
    assert any("different agent versions" in note for note in notes)
    assert compare_reports(before, after).comparable
