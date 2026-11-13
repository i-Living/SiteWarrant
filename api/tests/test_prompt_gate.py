from datetime import UTC, datetime

import pytest

from app.eval.gate import decide
from app.eval.models import EvalRun, RunContext


def run(*, digest: str = "sha256:same", precision: float = 0.9, fp_rate: float = 0.1) -> EvalRun:
    return EvalRun(
        context=RunContext(
            dataset_digest=digest,
            dataset_version=1,
            agent_version="sha256:test",
            viewports=["390x844"],
            started_at=datetime(2026, 11, 13, tzinfo=UTC),
            finished_at=datetime(2026, 11, 13, 0, 1, tzinfo=UTC),
            duration_s=60.0,
        ),
        metrics={
            "precision": precision,
            "recall": 0.5,
            "false_positive_rate": fp_rate,
            "page_false_positive_rate": 0.2,
            "duplicate_rate": 0.0,
            "per_rule": {},
        },
        per_site={},
    )


def test_a_precise_change_is_accepted() -> None:
    decision = decide(run(precision=0.9, fp_rate=0.1), run(precision=0.95, fp_rate=0.05))
    assert decision.accepted
    assert decision.verdict == "accept"
    assert decision.deltas["precision"] > 0


def test_a_change_that_holds_precision_is_accepted_even_when_recall_moves() -> None:
    # Recall is not the gate: a prompt may find more. Precision is what protects the reader.
    decision = decide(run(precision=0.9), run(precision=0.9))
    assert decision.accepted
    assert decision.deltas["precision"] == 0.0


def test_a_change_that_loses_precision_is_rejected() -> None:
    decision = decide(run(precision=0.9), run(precision=0.86))
    assert not decision.accepted
    assert decision.verdict == "reject"
    assert any("precision" in reason for reason in decision.reasons)


def test_a_change_that_raises_the_false_positive_rate_is_rejected() -> None:
    decision = decide(run(precision=0.9, fp_rate=0.05), run(precision=0.9, fp_rate=0.12))
    assert not decision.accepted
    assert any("false_positive_rate" in reason for reason in decision.reasons)


def test_tolerance_buys_noise_not_a_regression() -> None:
    assert decide(run(precision=0.9), run(precision=0.895), tolerance=0.01).accepted
    assert not decide(run(precision=0.9), run(precision=0.85), tolerance=0.01).accepted


def test_two_runs_on_different_corpora_are_not_evidence() -> None:
    decision = decide(
        run(digest="sha256:one", precision=0.5), run(digest="sha256:two", precision=1.0)
    )
    assert not decision.accepted
    assert decision.deltas == {}
    assert "different corpora" in " ".join(decision.reasons)


def test_the_decision_names_the_corpus_it_was_made_on() -> None:
    decision = decide(run(digest="sha256:corpus"), run(digest="sha256:corpus"))
    assert decision.corpus == "sha256:corpus"


@pytest.mark.parametrize("field", ["precision", "false_positive_rate"])
def test_gated_metrics_are_always_reported(field: str) -> None:
    decision = decide(run(), run())
    assert field in decision.deltas
