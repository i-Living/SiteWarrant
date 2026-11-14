"""The re-audit delta keeps enough of a finding to say which one closed."""

import tempfile
from pathlib import Path

import pytest

from app.core.report import FindingOut, ImpactOut
from app.fixes.reaudit import ReauditError, apply_patch, diff_findings


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


def copies() -> set[Path]:
    return set(Path(tempfile.gettempdir()).glob("sitewarrant-reaudit-*"))


def test_a_rejected_patch_leaves_no_copy_of_the_site_behind(tmp_path: Path) -> None:
    """The measurement keeps going after a repair fails, so a leak here is one copy per failure."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<html></html>", encoding="utf-8")
    patch = tmp_path / "repair.patch"
    patch.write_text(
        "--- a/missing.html\n+++ b/missing.html\n@@ -1 +1 @@\n-old\n+new\n", encoding="utf-8"
    )

    before = copies()
    with pytest.raises(ReauditError, match="patch failed"):
        apply_patch(site, patch)
    assert copies() == before


def test_a_patch_that_applies_is_left_in_place(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text('<html lang="xx"></html>\n', encoding="utf-8")
    patch = tmp_path / "repair.patch"
    patch.write_text(
        "--- a/index.html\n+++ b/index.html\n@@ -1 +1 @@\n"
        '-<html lang="xx"></html>\n+<html lang="en"></html>\n',
        encoding="utf-8",
    )

    copy = apply_patch(site, patch)
    try:
        assert (copy / "index.html").read_text(encoding="utf-8") == '<html lang="en"></html>\n'
    finally:
        import shutil

        shutil.rmtree(copy.parent, ignore_errors=True)
