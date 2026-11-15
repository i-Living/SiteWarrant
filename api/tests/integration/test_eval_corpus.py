"""The corpus is frozen: this test fails when a page, a label or a run drifts apart."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.eval.runner import run_eval

pytestmark = [pytest.mark.integration, pytest.mark.corpus]

ROOT = Path(__file__).resolve().parents[3]
BENCHMARK = ROOT / "benchmark"


def test_the_generator_reproduces_the_committed_corpus() -> None:
    """A hand-edited page would make its label a lie; `--check` compares every byte."""
    result = subprocess.run(
        [sys.executable, str(BENCHMARK / "generate.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "corpus matches the generator" in result.stdout


async def test_one_site_of_the_corpus_is_measured_twice_and_describes_itself() -> None:
    """One site, two passes, one run file: the numbers repeat and the run says how it got them.

    The two passes, the self-description and the screenshot check share one test on purpose: a
    single eval spends a whole site of browser work, so a second site audited only to look at the
    payload, or a third one audited only to list the disk, would pay that price again for facts the
    run in hand already carries.
    """

    def screenshots() -> set[Path]:
        return set(get_settings().artifacts_dir.resolve().rglob("*.png"))

    before = await asyncio.to_thread(screenshots)
    first = await run_eval(BENCHMARK / "dataset.json", sites=["northwind"], store_artifacts=False)
    after_first = await asyncio.to_thread(screenshots)
    # An eval writes no screenshots: compare with what was on disk, not with zero.
    assert first.context.store_artifacts is False
    assert after_first - before == set(), (
        "an eval run must not spend disk on screenshots it never reads"
    )

    payload = json.loads(first.model_dump_json())
    assert payload["context"]["dataset_digest"].startswith("sha256:")
    assert payload["context"]["agent_version"].startswith("sha256:")
    assert payload["context"]["viewports"]
    assert set(payload["metrics"]) >= {"precision", "recall", "false_positive_rate", "per_rule"}
    # The corpus's own denominator travels with the run, so a reader can redo the arithmetic.
    assert payload["metrics"]["labels"] == sum(
        rule["labels"] for rule in payload["metrics"]["per_rule"].values()
    )

    second = await run_eval(BENCHMARK / "dataset.json", sites=["northwind"], store_artifacts=False)
    assert first.metrics["labels"] == 10
    assert first.metrics["pages"] == 13
    for field in ("predicted", "true_positives", "false_positives", "false_negatives"):
        assert first.metrics[field] == second.metrics[field], field
    assert [item.rule_id for item in first.missing] == [item.rule_id for item in second.missing]
    assert [item.rule_id for item in first.extra] == [item.rule_id for item in second.extra]
    assert first.metrics["duplicate_rate"] == 0.0
    # The second pass wrote nothing either.
    assert await asyncio.to_thread(screenshots) - before == set()
