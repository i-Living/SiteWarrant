"""The gate a proposed prompt change has to pass.

A prompt edit is a hypothesis: "this wording finds more". Only the benchmark can settle it, and the
only claim the plan allows to gate on is precision — a change that buys recall by inventing findings
is a regression the product cannot afford, because every finding is supposed to carry a citation a
reader can follow.

Two runs on different corpora are not evidence of anything: `decide` refuses them rather than
comparing numbers that were measured against different label sets.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.eval.compare import compare_runs
from app.eval.models import EvalRun

GATED = ("precision", "false_positive_rate")


@dataclass
class GateDecision:
    accepted: bool
    reasons: list[str] = field(default_factory=list)
    deltas: dict[str, float] = field(default_factory=dict)
    corpus: str | None = None

    @property
    def verdict(self) -> str:
        return "accept" if self.accepted else "reject"


def decide(baseline: EvalRun, candidate: EvalRun, *, tolerance: float = 0.0) -> GateDecision:
    """Accept a change only when precision did not drop and the false-positive rate did not rise.

    `tolerance` exists for measurement noise, not for buying a regression: it defaults to zero, so
    a change has to be at least as precise as the one it replaces.
    """
    comparison = compare_runs(baseline, candidate)
    if not comparison.compatible:
        return GateDecision(
            accepted=False,
            reasons=[comparison.note or "the two runs cannot be compared"],
            corpus=baseline.context.dataset_digest,
        )

    decision = GateDecision(accepted=True, corpus=baseline.context.dataset_digest)
    for name in GATED:
        before = float(baseline.metrics.get(name, 0.0))
        after = float(candidate.metrics.get(name, 0.0))
        delta = round(after - before, 4)
        decision.deltas[name] = delta
        worse = delta < -tolerance if name == "precision" else delta > tolerance
        if worse:
            decision.accepted = False
            decision.reasons.append(
                f"{name} moved the wrong way: {before:.4f} → {after:.4f} ({delta:+.4f})"
            )
    if not decision.reasons:
        decision.reasons.append(
            "precision and false-positive rate held: "
            + ", ".join(f"{name} {delta:+.4f}" for name, delta in decision.deltas.items())
        )
    return decision
