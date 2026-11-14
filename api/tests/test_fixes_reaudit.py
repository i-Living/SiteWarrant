"""The re-audit delta keeps enough of a finding to say which one closed."""

from app.core.report import FindingOut, ImpactOut
from app.fixes.reaudit import diff_findings


def finding(rule_id: str, subject: str, page: str = "http://x/products/item-2.html") -> FindingOut:
    return FindingOut(
        id=f"{rule_id}:{subject}",
        rule_id=rule_id,
        category="layout",
        severity="major",
        title="covered",
        summary="a banner covers the link",
        suggested_fix="move the banner",
        impact=ImpactOut(conversion=1, seo=0, ux=1),
        confidence=1.0,
        agent="layout",
        page_url=page,
        page_key=page,
        subject=subject,
        evidence=[],
    )


def test_a_delta_carries_the_subject_that_identifies_the_finding() -> None:
    """Two findings of one rule are two findings; the rule alone cannot tell them apart."""
    before = [
        finding("LAYOUT-OCCLUSION", "main > a:nth-of-type(1)"),
        finding("LAYOUT-OCCLUSION", "main > a:nth-of-type(2)"),
    ]
    after = [finding("LAYOUT-OCCLUSION", "main > a:nth-of-type(2)")]
    result = diff_findings(before, after)

    assert [item.subject for item in result.closed] == ["main > a:nth-of-type(1)"]
    assert [item.subject for item in result.remaining] == ["main > a:nth-of-type(2)"]
    assert result.new == []


def test_a_finding_that_moved_subject_is_a_regression_and_a_closure() -> None:
    before = [finding("A11Y-LANG", "html")]
    after = [finding("A11Y-LANG", "html:nth-of-type(1)")]
    result = diff_findings(before, after)

    assert [item.subject for item in result.closed] == ["html"]
    assert [item.subject for item in result.regressions] == ["html:nth-of-type(1)"]
