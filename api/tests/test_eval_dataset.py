import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.eval.compare import compare_runs
from app.eval.dataset import DatasetError, Label, SiteLabels, dataset_digest, load_dataset
from app.eval.models import EvalRun, RunContext

BENCHMARK = Path(__file__).resolve().parents[2] / "benchmark" / "dataset.json"


def run(digest: str = "sha256:aaaa", precision: float = 1.0, recall: float = 1.0) -> EvalRun:
    context = RunContext(
        dataset_digest=digest,
        dataset_version=1,
        agent_version="sha256:test",
        viewports=["390x844"],
        started_at=datetime(2026, 11, 13, tzinfo=UTC),
        finished_at=datetime(2026, 11, 13, 0, 1, tzinfo=UTC),
        duration_s=60.0,
    )
    return EvalRun(
        context=context,
        metrics={
            "precision": precision,
            "recall": recall,
            "false_positive_rate": round(1 - precision, 4),
            "page_false_positive_rate": 0.0,
            "duplicate_rate": 0.0,
            "per_rule": {
                "SEO-TITLE": {"precision": precision, "recall": recall},
                "A11Y-LANG": {"precision": precision, "recall": recall},
            },
        },
        per_site={},
    )


def test_the_committed_corpus_is_whole() -> None:
    dataset = load_dataset(BENCHMARK)
    assert len(dataset.sites) >= 8
    assert dataset.pages >= 100
    assert dataset.labels >= 80
    assert dataset.digest.startswith("sha256:")
    assert dataset.digest == dataset_digest(dataset.sites)
    assert len(dataset.rules()) == 10


def test_every_site_plants_each_rule_exactly_once() -> None:
    dataset = load_dataset(BENCHMARK)
    for site in dataset.sites:
        planted = [label.rule_id for label in site.labels]
        assert len(planted) == 10, site.slug
        assert len(set(planted)) == 10, site.slug
        assert len(site.pages) == 13, site.slug
        # Three clean pages per site: the control for false positives.
        assert len(site.pages) - len(site.labels) == 3, site.slug


def test_a_label_for_an_unknown_page_is_refused(tmp_path: Path) -> None:
    payload = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    payload["sites"][0]["labels"][0]["page"] = "nowhere.html"
    broken = tmp_path / "dataset.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DatasetError, match="unknown page"):
        load_dataset(broken)


def test_a_digest_that_does_not_describe_the_labels_is_refused(tmp_path: Path) -> None:
    """A comparison trusts the digest, so a manifest may not carry someone else's."""
    payload = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    payload["digest"] = "sha256:0000000000000000"
    broken = tmp_path / "dataset.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DatasetError, match="does not match the corpus"):
        load_dataset(broken)


def test_the_digest_names_the_markup_not_only_the_labels() -> None:
    """Same labels, different pages: a run on one is not a run on the other."""
    labels = (Label(page="index.html", rule_id="SEO-TITLE"),)
    one = SiteLabels(
        slug="lumen",
        base_url="http://bench/lumen/",
        pages=("index.html",),
        labels=labels,
        page_digests={"index.html": "sha256:0000000000000001"},
    )
    other = SiteLabels(
        slug="lumen",
        base_url="http://bench/lumen/",
        pages=("index.html",),
        labels=labels,
        page_digests={"index.html": "sha256:0000000000000002"},
    )
    assert dataset_digest((one,)) != dataset_digest((other,))
    # The labels alone would have called these the same corpus.
    assert [(label.page, label.rule_id) for label in one.labels] == [
        (label.page, label.rule_id) for label in other.labels
    ]


def test_a_page_without_a_content_digest_is_refused(tmp_path: Path) -> None:
    payload = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    payload["sites"][0]["page_digests"].pop("index.html")
    broken = tmp_path / "dataset.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DatasetError, match="no content digest"):
        load_dataset(broken)


def test_a_small_corpus_is_refused(tmp_path: Path) -> None:
    payload = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    payload["sites"] = payload["sites"][:2]
    # The digest would now describe a corpus that no longer exists; the size rule is under test.
    payload.pop("digest", None)
    small = tmp_path / "dataset.json"
    small.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DatasetError, match="at least 8 sites"):
        load_dataset(small)


def test_an_unknown_site_is_named_with_the_available_ones() -> None:
    dataset = load_dataset(BENCHMARK)
    with pytest.raises(DatasetError, match="unknown site"):
        dataset.site("does-not-exist")


def test_two_runs_on_one_corpus_compare() -> None:
    comparison = compare_runs(run(precision=0.9, recall=0.9), run(precision=1.0, recall=0.85))
    assert comparison.compatible
    assert comparison.deltas["precision"] == 0.1
    assert comparison.deltas["recall"] == -0.05
    # Precision improved and recall dropped: a rule that loses a label is a regression, so the
    # comparison is not allowed to call this round an improvement.
    assert set(comparison.regressions) == {"SEO-TITLE", "A11Y-LANG"}
    assert comparison.improvements == []


def test_runs_on_different_corpora_refuse_to_compare() -> None:
    comparison = compare_runs(run(digest="sha256:one"), run(digest="sha256:two"))
    assert not comparison.compatible
    assert comparison.deltas == {}
    assert "different corpora" in comparison.note
