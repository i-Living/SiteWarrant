import pytest

from app.eval.metrics import measure


def label(rule: str, page: str) -> tuple[str, str]:
    return (rule, page)


def test_every_ratio_carries_its_denominator() -> None:
    metrics = measure(
        {label("SEO-TITLE", "index.html"), label("A11Y-LANG", "about.html")},
        {label("SEO-TITLE", "index.html"), label("A11Y-CONTRAST", "index.html")},
        pages=10,
        pages_with_false_positives=1,
        findings_raw=4,
        duplicates_removed=2,
        all_rules={"SEO-TITLE", "A11Y-LANG", "A11Y-CONTRAST"},
    )
    assert (metrics.true_positives, metrics.false_positives, metrics.false_negatives) == (1, 1, 1)
    assert metrics.precision == 0.5
    assert metrics.recall == 0.5
    assert metrics.false_positive_rate == 0.5
    assert metrics.page_false_positive_rate == 0.1
    assert metrics.duplicate_rate == 0.5


def test_a_perfect_run_is_one_and_zero() -> None:
    labels = {label("SEO-TITLE", "index.html"), label("A11Y-LANG", "about.html")}
    metrics = measure(
        labels,
        set(labels),
        pages=2,
        pages_with_false_positives=0,
        findings_raw=2,
        duplicates_removed=0,
    )
    assert (metrics.precision, metrics.recall, metrics.false_positive_rate) == (1.0, 1.0, 0.0)
    assert metrics.duplicate_rate == 0.0


def test_no_predictions_is_zero_precision_not_a_division_error() -> None:
    metrics = measure(
        {label("SEO-TITLE", "index.html")},
        set(),
        pages=1,
        pages_with_false_positives=0,
        findings_raw=0,
        duplicates_removed=0,
    )
    assert metrics.precision == 0.0
    assert metrics.recall == 0.0
    assert metrics.false_positive_rate == 0.0


def test_per_rule_counts_add_up_to_the_totals() -> None:
    labels = {
        label("SEO-TITLE", "a.html"),
        label("SEO-TITLE", "b.html"),
        label("A11Y-LANG", "c.html"),
    }
    predicted = {label("SEO-TITLE", "a.html"), label("A11Y-LANG", "d.html")}
    metrics = measure(
        labels,
        predicted,
        pages=4,
        pages_with_false_positives=1,
        findings_raw=2,
        duplicates_removed=0,
        all_rules={"SEO-TITLE", "A11Y-LANG", "LAYOUT-OCCLUSION"},
    )
    assert sum(rule.labels for rule in metrics.per_rule.values()) == metrics.labels
    assert sum(rule.predicted for rule in metrics.per_rule.values()) == metrics.predicted
    assert metrics.per_rule["LAYOUT-OCCLUSION"].labels == 0
    assert metrics.per_rule["SEO-TITLE"].recall == 0.5
    assert metrics.per_rule["A11Y-LANG"].precision == 0.0


@pytest.mark.parametrize("field", ["precision", "recall", "false_positive_rate", "duplicate_rate"])
def test_ratios_are_between_zero_and_one(field: str) -> None:
    metrics = measure(
        {label("SEO-TITLE", "a.html")},
        {label("SEO-TITLE", "a.html")},
        pages=1,
        pages_with_false_positives=0,
        findings_raw=1,
        duplicates_removed=0,
    )
    assert 0.0 <= getattr(metrics, field) <= 1.0
