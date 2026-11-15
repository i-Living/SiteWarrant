"""Measured fix acceptance on one corpus site: the repairs apply, they close, they break nothing."""

from pathlib import Path

import pytest

from app.eval.dataset import DatasetError, load_dataset
from app.fixes.measure import measure_fixes
from app.fixes.patch import FIXABLE

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[3]
BENCHMARK = ROOT / "benchmark"


@pytest.mark.corpus
async def test_every_fixable_rule_is_proposed_applied_and_closed() -> None:
    """One site plants one defect per rule, plus a second link covered by the same banner."""
    run = await measure_fixes(BENCHMARK / "dataset.json", sites=["northwind"])

    assert run.context.dataset_digest == load_dataset(BENCHMARK / "dataset.json").digest
    assert run.not_applied == []
    assert set(run.per_rule) == set(FIXABLE)
    # Six findings of mechanically fixable rules: five rules, one of them twice — the banner covers
    # two links and each covered target is its own finding.
    assert run.totals.findings == len(FIXABLE) + 1
    assert run.totals.proposed == run.totals.findings
    assert run.totals.applied == run.totals.proposed
    # A mechanical repair that does not close the finding it was computed for is a broken fixer.
    assert run.totals.closed == run.totals.applied
    assert run.totals.regression_free == run.totals.applied
    assert run.totals.fix_acceptance_rate == 1.0
    assert run.totals.regression_free_fix_rate == 1.0
    assert set(run.per_site) == {"northwind"}


async def test_an_unknown_site_is_refused() -> None:
    """A silent subset would be a shorter denominator, which is a different measurement."""
    with pytest.raises(DatasetError, match="unknown site"):
        await measure_fixes(BENCHMARK / "dataset.json", sites=["no-such-site"])
