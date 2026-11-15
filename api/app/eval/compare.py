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
    # A metric with no denominator is `None`, and a delta needs both sides: comparing against an
    # unknown would report a change nobody measured.
    deltas: dict[str, float | None]
    per_rule: dict[str, dict[str, float | None]]
    regressions: list[str] = []
    improvements: list[str] = []
    compatible: bool
    note: str = ""


def _delta(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return round(after - before, 4)


def compare_runs(
    baseline: EvalRun,
    candidate: EvalRun,
    *,
    baseline_label: str = "baseline",
    candidate_label: str = "candidate",
    allow_corpus_change: bool = False,
) -> Comparison:
    """A metric may only be compared across the same corpus; anything else is a different test."""
    same_digest = baseline.context.dataset_digest == candidate.context.dataset_digest
    # A subset of the corpus shares its digest but not its measurement: two sites cannot be
    # compared with eight and called a change.
    same_sites = set(baseline.per_site) == set(candidate.per_site)
    compatible = same_digest and same_sites
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
                "the two runs cannot be compared: "
                + (
                    "different corpora "
                    f"({baseline.context.dataset_digest} vs {candidate.context.dataset_digest})"
                    if not same_digest
                    else f"different site sets ({sorted(baseline.per_site)} vs "
                    f"{sorted(candidate.per_site)}) of one corpus"
                )
                + "; a delta across different measurements is not a comparison"
            ),
        )

    deltas = {
        metric: _delta(baseline.metrics.get(metric), candidate.metrics.get(metric))
        for metric in METRICS
    }
    per_rule: dict[str, dict[str, float | None]] = {}
    regressions: list[str] = []
    improvements: list[str] = []
    baseline_rules = baseline.metrics.get("per_rule", {})
    candidate_rules = candidate.metrics.get("per_rule", {})
    for rule in sorted(set(baseline_rules) | set(candidate_rules)):
        # A rule absent from one run was not measured there, which is not the same as zero.
        before = baseline_rules.get(rule, {})
        after = candidate_rules.get(rule, {})
        delta_precision = _delta(before.get("precision"), after.get("precision"))
        delta_recall = _delta(before.get("recall"), after.get("recall"))
        per_rule[rule] = {"precision": delta_precision, "recall": delta_recall}
        moved_down = any(
            delta is not None and delta < 0 for delta in (delta_recall, delta_precision)
        )
        moved_up = any(delta is not None and delta > 0 for delta in (delta_recall, delta_precision))
        if moved_down:
            regressions.append(rule)
        elif moved_up:
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
