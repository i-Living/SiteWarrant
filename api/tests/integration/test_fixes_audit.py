"""Fixes against a real audit: a patch closes a finding, an invented defect becomes a regression."""

from pathlib import Path

import pytest

from app.audit import run_audit
from app.fixes.patch import Patch
from app.fixes.reaudit import ReauditError, reaudit
from app.fixes.recommend import build_fixes, unified_diff, write_fix_files

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).resolve().parents[3] / "benchmark" / "fixtures" / "site"
URL = "http://localhost:8081/"


async def test_every_finding_gets_a_recommendation(tmp_path: Path) -> None:
    report = await run_audit(URL, allow_private=True)
    fixes = await build_fixes(report.audit_id, site_dir=FIXTURE)

    assert len(fixes.recommendations) == len(report.findings)
    assert all(item.text.strip() for item in fixes.recommendations)
    patched = {item.rule_id for item in fixes.recommendations if item.patched}
    # The five mechanical rules are paid for here; the rest are text on purpose.
    assert {"SEO-TITLE", "SEO-META-DESC", "SEO-H1", "A11Y-LANG", "LAYOUT-OCCLUSION"} <= patched
    assert "A11Y-IMG-ALT" not in patched
    # An occlusion patch moves the covering element; the covered link stays where it is.
    assert ".banner" in fixes.diff, fixes.diff[:400]
    advisory = [item for item in fixes.recommendations if not item.patched]
    assert all(item.note for item in advisory)

    written = write_fix_files(fixes, tmp_path / "fixes")
    assert (written / "recommendations.md").read_text(encoding="utf-8").count("## ") == len(
        fixes.recommendations
    )
    assert "--- a/" in (written / "fixes.patch").read_text(encoding="utf-8")


async def test_the_patch_closes_its_findings_and_adds_nothing(tmp_path: Path) -> None:
    """Apply the real patch to a copy of the fixture and re-audit it."""
    report = await run_audit(URL, allow_private=True)
    fixes = await build_fixes(report.audit_id, site_dir=FIXTURE)
    write_fix_files(fixes, tmp_path / "fixes")
    patch_file = tmp_path / "fixes" / "fixes.patch"
    assert patch_file.read_text(encoding="utf-8").strip()

    result = await reaudit(report, site_dir=FIXTURE, patch_file=patch_file)

    closed = {item.rule_id for item in result.closed}
    remaining = {item.rule_id for item in result.remaining}
    assert "SEO-TITLE" in closed, result.closed
    assert "A11Y-LANG" in closed
    assert remaining & {"SEO-TITLE", "A11Y-LANG"} == set()
    assert result.regressions == [], [item.rule_id for item in result.regressions]


async def test_an_invented_defect_lands_in_the_regressions(tmp_path: Path) -> None:
    """A fix that closes one finding and introduces another must not look like progress."""
    report = await run_audit(URL, allow_private=True)
    page = (FIXTURE / "index.html").read_text(encoding="utf-8")
    broken = page.replace(
        "<h2>",
        '<input type="email" name="email">\n      <h2>',
        1,
    )
    assert broken != page
    patch = Patch(
        rule_id="SEO-TITLE",
        page_url=URL,
        before=page,
        after=broken.replace("<h2>", "<title>Field notes</title>\n      <h2>", 1),
        note="closes the title and, accidentally, drops a label",
    )
    patch_file = tmp_path / "broken.patch"
    patch_file.write_text(unified_diff(patch, path="index.html"), encoding="utf-8")

    # The baseline knows one defect; everything else the page reports afterwards is new to it.
    baseline = report.model_copy(
        update={"findings": [item for item in report.findings if item.rule_id == "SEO-TITLE"]}
    )
    result = await reaudit(baseline, site_dir=FIXTURE, patch_file=patch_file)

    regressed = {item.rule_id for item in result.regressions}
    assert "A11Y-LABEL" in regressed, [item.rule_id for item in result.regressions]
    assert "SEO-TITLE" in {item.rule_id for item in result.closed}


async def test_a_patch_without_a_site_directory_is_refused() -> None:
    report = await run_audit(URL, allow_private=True)
    with pytest.raises(ReauditError, match="site-dir"):
        await reaudit(report, patch_file=Path("nowhere.patch"))


def test_an_unappliable_patch_is_refused(tmp_path: Path) -> None:
    page = (FIXTURE / "index.html").read_text(encoding="utf-8")
    patch = Patch(
        rule_id="SEO-TITLE",
        page_url=URL,
        before=page,
        after=page.replace("</body>", "<!-- x -->\n</body>", 1),
        note="harmless",
    )
    bogus = tmp_path / "bogus.patch"
    bogus.write_text(
        unified_diff(patch, path="index.html").replace("</body>", "</not-on-this-page>"),
        encoding="utf-8",
    )
    with pytest.raises(ReauditError, match="patch failed"):
        from app.fixes.reaudit import apply_patch

        apply_patch(FIXTURE, bogus)
