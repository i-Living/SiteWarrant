"""The corpus is frozen: this test fails when a page and its labels drift apart."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.eval.runner import run_eval

pytestmark = pytest.mark.integration

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


async def test_one_site_of_the_corpus_scores_repeatably() -> None:
    """Two passes over one site report the same findings, so the numbers are not a coin flip."""
    first = await run_eval(BENCHMARK / "dataset.json", sites=["northwind"], store_artifacts=False)
    second = await run_eval(BENCHMARK / "dataset.json", sites=["northwind"], store_artifacts=False)

    assert first.metrics["labels"] == 10
    assert first.metrics["pages"] == 13
    for field in ("predicted", "true_positives", "false_positives", "false_negatives"):
        assert first.metrics[field] == second.metrics[field], field
    assert [item.rule_id for item in first.missing] == [item.rule_id for item in second.missing]
    assert [item.rule_id for item in first.extra] == [item.rule_id for item in second.extra]
    assert first.metrics["duplicate_rate"] == 0.0


async def test_a_run_is_self_describing() -> None:
    run = await run_eval(BENCHMARK / "dataset.json", sites=["saltmarsh"], store_artifacts=False)
    payload = json.loads(run.model_dump_json())
    assert payload["context"]["dataset_digest"].startswith("sha256:")
    assert payload["context"]["agent_version"].startswith("sha256:")
    assert payload["context"]["viewports"]
    assert set(payload["metrics"]) >= {"precision", "recall", "false_positive_rate", "per_rule"}
    assert payload["context"]["store_artifacts"] is False
    # The corpus's own denominator travels with the run, so a reader can redo the arithmetic.
    assert payload["metrics"]["labels"] == sum(
        rule["labels"] for rule in payload["metrics"]["per_rule"].values()
    )


async def test_artifacts_are_off_by_default() -> None:
    """An eval writes no screenshots: compare with what was on disk, not with zero."""
    artifacts = os.environ.get("ARTIFACTS_DIR")
    if not artifacts:
        pytest.skip("ARTIFACTS_DIR is not set, so there is nothing to inspect")

    def screenshots() -> set[Path]:
        return set(Path(artifacts).rglob("*.png"))

    before = await asyncio.to_thread(screenshots)
    run = await run_eval(BENCHMARK / "dataset.json", sites=["lumen"], store_artifacts=False)
    after = await asyncio.to_thread(screenshots)

    assert run.context.store_artifacts is False
    assert after - before == set(), "an eval run must not spend disk on screenshots it never reads"
