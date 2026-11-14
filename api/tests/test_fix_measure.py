"""A repair is counted against the finding it was computed for, and against the corpus it served."""

from pathlib import Path

import pytest

from app.eval.dataset import DatasetError, SiteLabels, page_digest
from app.fixes.measure import closed_by, verify_sources
from app.fixes.patch import Patch
from app.fixes.reaudit import Delta


def repair(rule_id: str, subject: str) -> Patch:
    return Patch(
        rule_id=rule_id, page_url="http://x/", before="", after="", note="", subject=subject
    )


def closed(rule_id: str, subject: str) -> Delta:
    return Delta(rule_id=rule_id, page_url="http://x/", severity="major", subject=subject)


def test_a_closure_belongs_to_the_finding_it_names() -> None:
    """One banner covering two links closes two findings; one repair answers for one of them."""
    vulnerability = repaired = repair("LAYOUT-OCCLUSION", "main > p:nth-of-type(2) > a")
    other = closed("LAYOUT-OCCLUSION", "main > p:nth-of-type(3) > a")
    assert not closed_by([other], vulnerability)
    assert closed_by([other, closed("LAYOUT-OCCLUSION", "main > p:nth-of-type(2) > a")], repaired)


def test_a_closed_finding_of_another_rule_is_not_a_closure() -> None:
    assert not closed_by(
        [closed("SEO-TITLE", "main > p:nth-of-type(2) > a")], repair("SEO-TITLE", "")
    )


def test_a_subject_less_finding_matches_only_a_subject_less_repair() -> None:
    """`key_of` names a subjectless finding by its rule and page alone; equality says the same."""
    assert closed_by([closed("SEO-H1", "")], repair("SEO-H1", ""))
    assert not closed_by([closed("SEO-H1", "h1")], repair("SEO-H1", ""))


def site(tmp_path: Path, source: str) -> SiteLabels:
    (tmp_path / "index.html").write_text(source, encoding="utf-8")
    return SiteLabels(
        slug="northwind",
        base_url="http://127.0.0.1:8088",
        pages=("index.html",),
        labels=(),
        page_digests={"index.html": page_digest(source)},
    )


def test_sources_have_to_be_the_pages_the_manifest_digests(tmp_path: Path) -> None:
    """The manifest cannot see the files; an edited page would be measured under its identity."""
    known = site(tmp_path, "<html lang='en'></html>")
    verify_sources(known, tmp_path)
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    with pytest.raises(DatasetError, match="not the page the manifest digests"):
        verify_sources(known, tmp_path)


def test_a_missing_page_is_refused_instead_of_shrinking_the_denominator(tmp_path: Path) -> None:
    known = site(tmp_path, "<html></html>")
    (tmp_path / "index.html").unlink()
    with pytest.raises(DatasetError, match="no source file"):
        verify_sources(known, tmp_path)
