from app.core.report import (
    EvidenceOut,
    FindingOut,
    ImpactOut,
    Report,
    build_report,
    direction_score,
    exit_code_for,
    has_blocker,
)
from app.rules.catalog import Severity


def finding(
    severity: Severity,
    category: str = "a11y",
    rule_id: str = "A11Y-LANG",
) -> FindingOut:
    return FindingOut(
        id="finding",
        rule_id=rule_id,
        category=category,
        severity=severity,
        title="title",
        summary="summary",
        suggested_fix="fix",
        impact=ImpactOut(conversion=0, seo=0, ux=1),
        confidence=1.0,
        agent="rules",
        page_url="http://example.test/",
        page_key="example.test",
        evidence=[EvidenceOut(kind="dom", observation_id="observation")],
    )


def report_with(*findings: FindingOut, measured: set[str] | None = None) -> Report:
    return build_report(
        audit_id="audit",
        site="http://example.test/",
        agent_version="sha256:test",
        status="completed",
        findings=list(findings),
        pages_audited=1,
        duration_ms=42,
        measured_categories=measured or {"a11y"},
    )


def test_direction_score_is_capped() -> None:
    assert direction_score(0.0, 1) == 100.0
    assert direction_score(40.0, 1) == 0.0
    assert direction_score(400.0, 1) == 0.0


def test_direction_score_divides_penalty_by_pages() -> None:
    assert direction_score(8.0, 2) == 90.0


def test_direction_score_without_pages_is_zero() -> None:
    assert direction_score(0.0, 0) == 0.0


def test_report_counts_every_severity() -> None:
    report = report_with(finding("blocker"), finding("minor"))
    assert report.summary.by_severity == {"blocker": 1, "major": 0, "minor": 1, "info": 0}
    assert report.summary.findings_total == 2


def test_unmeasured_category_is_not_scored() -> None:
    report = report_with(finding("major", category="security"), measured={"a11y"})
    assert set(report.summary.scores) == {"a11y"}


def test_blocker_sets_exit_code_one() -> None:
    report = report_with(finding("blocker"))
    assert has_blocker(report) is True
    assert exit_code_for(report) == 1


def test_major_only_exits_clean() -> None:
    report = report_with(finding("major"))
    assert has_blocker(report) is False
    assert exit_code_for(report) == 0
