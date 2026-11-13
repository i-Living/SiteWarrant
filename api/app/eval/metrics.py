"""Metrics with denominators that survive a reader's arithmetic check."""

from __future__ import annotations

from dataclasses import dataclass, field


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


@dataclass(frozen=True)
class RuleMetrics:
    rule_id: str
    labels: int
    predicted: int
    true_positives: int

    @property
    def false_positives(self) -> int:
        return self.predicted - self.true_positives

    @property
    def false_negatives(self) -> int:
        return self.labels - self.true_positives

    @property
    def precision(self) -> float:
        return _ratio(self.true_positives, self.predicted)

    @property
    def recall(self) -> float:
        return _ratio(self.true_positives, self.labels)

    def as_dict(self) -> dict[str, float | int | str]:
        return {
            "rule_id": self.rule_id,
            "labels": self.labels,
            "predicted": self.predicted,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": self.precision,
            "recall": self.recall,
        }


@dataclass(frozen=True)
class Metrics:
    """Counts first, ratios second: every ratio has its denominator next to it."""

    pages: int
    labels: int
    predicted: int
    true_positives: int
    false_positives: int
    false_negatives: int
    pages_with_false_positives: int
    findings_raw: int
    duplicates_removed: int
    per_rule: dict[str, RuleMetrics] = field(default_factory=dict)

    @property
    def precision(self) -> float:
        return _ratio(self.true_positives, self.predicted)

    @property
    def recall(self) -> float:
        return _ratio(self.true_positives, self.labels)

    @property
    def false_positive_rate(self) -> float:
        """Share of reported findings that no label backs."""
        return _ratio(self.false_positives, self.predicted)

    @property
    def duplicate_rate(self) -> float:
        return _ratio(self.duplicates_removed, self.findings_raw)

    @property
    def page_false_positive_rate(self) -> float:
        """Share of pages that reported at least one finding nobody planted."""
        return _ratio(self.pages_with_false_positives, self.pages)

    def as_dict(self) -> dict[str, object]:
        return {
            "pages": self.pages,
            "labels": self.labels,
            "predicted": self.predicted,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "pages_with_false_positives": self.pages_with_false_positives,
            "findings_raw": self.findings_raw,
            "duplicates_removed": self.duplicates_removed,
            "precision": self.precision,
            "recall": self.recall,
            "false_positive_rate": self.false_positive_rate,
            "page_false_positive_rate": self.page_false_positive_rate,
            "duplicate_rate": self.duplicate_rate,
            "per_rule": {rule: item.as_dict() for rule, item in sorted(self.per_rule.items())},
        }


def measure(
    labels: set[tuple[str, str]],
    predicted: set[tuple[str, str]],
    *,
    pages: int,
    pages_with_false_positives: int,
    findings_raw: int,
    duplicates_removed: int,
    all_rules: set[str] | None = None,
) -> Metrics:
    """`(rule_id, page)` pairs: one label, one prediction, no selectors to reconcile."""
    true_positives = labels & predicted
    false_positives = predicted - labels
    false_negatives = labels - predicted
    rules = set(all_rules or set()) | {rule for rule, _ in labels | predicted}
    per_rule: dict[str, RuleMetrics] = {}
    for rule in sorted(rules):
        per_rule[rule] = RuleMetrics(
            rule_id=rule,
            labels=sum(1 for item in labels if item[0] == rule),
            predicted=sum(1 for item in predicted if item[0] == rule),
            true_positives=sum(1 for item in true_positives if item[0] == rule),
        )
    return Metrics(
        pages=pages,
        labels=len(labels),
        predicted=len(predicted),
        true_positives=len(true_positives),
        false_positives=len(false_positives),
        false_negatives=len(false_negatives),
        pages_with_false_positives=pages_with_false_positives,
        findings_raw=findings_raw,
        duplicates_removed=duplicates_removed,
        per_rule=per_rule,
    )
