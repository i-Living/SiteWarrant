"""The fix metrics: counts travel with their denominators, and a zero denominator is null."""

from app.fixes.measure import Counts, rate, with_rates


def test_a_rate_without_a_denominator_is_null_not_zero() -> None:
    """An unmeasured rate is not a perfect one, and it is not a zero either."""
    assert rate(0, 0) is None
    assert rate(3, 0) is None
    assert Counts().fix_acceptance_rate is None
    assert Counts().regression_free_fix_rate is None


def test_a_rate_keeps_four_places() -> None:
    assert rate(2, 3) == 0.6667
    assert rate(5, 5) == 1.0
    assert rate(0, 5) == 0.0


def test_every_bucket_gets_its_own_rates() -> None:
    counts = with_rates(Counts(proposed=8, applied=8, closed=7, regression_free=6))
    assert counts.fix_acceptance_rate == 1.0
    assert counts.regression_free_fix_rate == 0.75
    # The counts are the evidence for the ratios; rounding one must not move the other.
    assert (counts.proposed, counts.applied, counts.closed, counts.regression_free) == (8, 8, 7, 6)
