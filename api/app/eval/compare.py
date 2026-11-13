"""Compare two eval runs, refusing a comparison the corpus cannot support."""

from __future__ import annotations

from pydantic import BaseModel

from app.eval.models import EvalRun

METRICS = (
    "precision",
    "recall",
    "false_positive_rate",
    "page_false_positive_rate",
    "duplicate_rate",
)


class Comparison(BaseModel):
    baseline: str
    candidate: str
    dataset_digest: str
    agent_versions: dict[str, str]
    deltas: dict[str, float]
    per_rule: dict[str, dict[str, float]]
    regressions: list[str] = []
    improvements: list[str] = []
    compatible: bool
    note: str = ""


def compare_runs(
    baseline: EvalRun,
    candidate: EvalRun,
    *,
    baseline_label: str = "baseline",
    candidate_label: str = "candidate",
    allow_corpus_change: bool = False,
) -> Comparison:
    """A metric may only be compared across the same corpus; anything else is a different test."""
    compatible = baseline.context.dataset_digest == candidate.context.dataset_digest
    if not compatible and not allow_corpus_change:
        return Comparison(
            baseline=baseline_label,
            candidate=candidate_label,
            dataset_digest=baseline.context.dataset_digest,
            agent_versions={
                "baseline": baseline.context.agent_version,
                "candidate": candidate.context.agent_version,
            },
            deltas={},
            per_rule={},
            compatible=False,
            note=(
                "the two runs were measured on different corpora "
                f"({baseline.context.dataset_digest} vs {candidate.context.dataset_digest}); "
                "a delta across corpora is not a comparison"
            ),
        )

    deltas = {
        metric: round(float(candidate.metrics[metric]) - float(baseline.metrics[metric]), 4)
        for metric in METRICS
    }
    per_rule: dict[str, dict[str, float]] = {}
    regressions: list[str] = []
    improvements: list[str] = []
    baseline_rules = baseline.metrics.get("per_rule", {})
    candidate_rules = candidate.metrics.get("per_rule", {})
    for rule in sorted(set(baseline_rules) | set(candidate_rules)):
        before = baseline_rules.get(rule, {"precision": 0.0, "recall": 0.0})
        after = candidate_rules.get(rule, {"precision": 0.0, "recall": 0.0})
        delta_precision = round(float(after["precision"]) - float(before["precision"]), 4)
        delta_recall = round(float(after["recall"]) - float(before["recall"]), 4)
        per_rule[rule] = {"precision": delta_precision, "recall": delta_recall}
        if delta_recall < 0 or delta_precision < 0:
            regressions.append(rule)
        elif delta_recall > 0 or delta_precision > 0:
            improvements.append(rule)

    return Comparison(
        baseline=baseline_label,
        candidate=candidate_label,
        dataset_digest=baseline.context.dataset_digest,
        agent_versions={
            "baseline": baseline.context.agent_version,
            "candidate": candidate.context.agent_version,
        },
        deltas=deltas,
        per_rule=per_rule,
        regressions=regressions,
        improvements=improvements,
        compatible=True,
        note="same corpus: deltas are comparable",
    )
