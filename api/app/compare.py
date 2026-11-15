"""Compare two stored audits of one site: what closed, what stayed, what is new.

`diff_findings` already answers the per-finding question for a re-audit. This module adds the two
things comparing two *stored* audits needs: a comparability verdict, and the same diff grouped by
root cause, so a reader sees "the header banner still covers the menu" instead of forty rows.

A comparison across a different site or a disjoint page set is not a comparison and says so;
a comparison across a different `agent_version` is a comparison between two instruments, which
is allowed and labelled.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.core.report import FindingOut, Report
from app.fixes.reaudit import Delta, diff_findings, key_of, path_of

FindingKey = tuple[str, str, str]
CauseKey = tuple[str, str, str]


@dataclass(frozen=True)
class CauseDelta:
    """One root cause's count in the diff. The anchor and page are the cause's identity."""

    anchor: str
    page: str
    label: str
    closed: int
    new: int
    remaining: int


@dataclass
class Comparison:
    before: str
    after: str
    before_version: str
    after_version: str
    comparable: bool
    # A reason is why the two runs are not one measurement; a note is what a reader must know
    # to read the difference correctly.
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    closed: list[Delta] = field(default_factory=list)
    remaining: list[Delta] = field(default_factory=list)
    new: list[Delta] = field(default_factory=list)
    causes: list[CauseDelta] = field(default_factory=list)


def pages_of(report: Report) -> set[str]:
    return {path_of(finding.page_url) for finding in report.findings} or {path_of(report.site)}


def comparability(before: Report, after: Report) -> tuple[list[str], list[str]]:
    """(reasons, notes): the first says "not a comparison", the second "read it like this"."""
    reasons: list[str] = []
    notes: list[str] = []
    if before.site != after.site:
        reasons.append(f"different sites: {before.site} and {after.site}")
    if not pages_of(before) & pages_of(after):
        reasons.append("the two audits share no page path, so there is nothing to compare")
    if before.agent_version != after.agent_version:
        notes.append(
            "different agent versions "
            f"({before.agent_version} and {after.agent_version}): the difference is between "
            "two instruments, not a like-for-like measurement"
        )
    return reasons, notes


def _cause_counter(findings: list[FindingOut], report: Report) -> Counter[CauseKey]:
    anchors = {cause.id: cause for cause in report.root_causes}
    counts: Counter[CauseKey] = Counter()
    for finding in findings:
        cause = anchors.get(finding.root_cause_id or "")
        if cause is None:
            continue
        counts[(cause.anchor, path_of(finding.page_url), cause.label)] += 1
    return counts


def compare_reports(before: Report, after: Report) -> Comparison:
    reasons, notes = comparability(before, after)
    result = diff_findings(list(before.findings), list(after.findings))

    previous = {key_of(finding): finding for finding in before.findings}
    current = {key_of(finding): finding for finding in after.findings}
    closed = [previous[key] for key in previous.keys() - current.keys()]
    new = [current[key] for key in current.keys() - previous.keys()]
    remaining = [current[key] for key in previous.keys() & current.keys()]

    closed_counts = _cause_counter(closed, before)
    new_counts = _cause_counter(new, after)
    remaining_counts = _cause_counter(remaining, after)

    causes: list[CauseDelta] = []
    for key in sorted(set(closed_counts) | set(new_counts) | set(remaining_counts)):
        anchor, page, label = key
        causes.append(
            CauseDelta(
                anchor=anchor,
                page=page,
                label=label,
                closed=closed_counts[key],
                new=new_counts[key],
                remaining=remaining_counts[key],
            )
        )

    return Comparison(
        before=str(before.audit_id),
        after=str(after.audit_id),
        before_version=before.agent_version,
        after_version=after.agent_version,
        comparable=not reasons,
        reasons=reasons,
        notes=notes,
        closed=result.closed,
        remaining=result.remaining,
        new=result.new,
        causes=causes,
    )


__all__ = [
    "CauseDelta",
    "Comparison",
    "comparability",
    "compare_reports",
    "pages_of",
]
