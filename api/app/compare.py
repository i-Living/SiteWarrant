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
from collections.abc import Sequence

from pydantic import BaseModel, Field

from app.core.report import FindingOut, Report
from app.fixes.reaudit import Delta, diff_findings, key_of, path_of

FindingKey = tuple[str, str, str]
# A root cause is a place: the anchor inside a page. Its display label is not part of the identity,
# because two reports may spell the same place's tag differently (or not at all).
CauseKey = tuple[str, str]


class CauseDelta(BaseModel):
    """One root cause's count in the diff. The anchor and page are the cause's identity."""

    anchor: str
    page: str
    label: str
    closed: int
    new: int
    remaining: int


class Comparison(BaseModel):
    before: str
    after: str
    before_version: str
    after_version: str
    comparable: bool
    # A reason is why the two runs are not one measurement; a note is what a reader must know
    # to read the difference correctly.
    reasons: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    closed: list[Delta] = Field(default_factory=list)
    remaining: list[Delta] = Field(default_factory=list)
    new: list[Delta] = Field(default_factory=list)
    causes: list[CauseDelta] = Field(default_factory=list)


def pages_of(report: Report) -> set[str]:
    """The pages the audit covered, not the pages that happened to have a finding.

    A page that was audited and came back clean is still part of the comparison: reading coverage
    off the findings would call a repaired page "not audited" and refuse a valid comparison.
    Older reports have no `pages` list, so their findings are the only evidence of coverage.
    """
    pages = {path_of(page) if "://" in page else page for page in report.pages}
    if pages:
        return pages
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


def _cause_counter(
    findings: Sequence[FindingOut], report: Report
) -> tuple[Counter[CauseKey], dict[CauseKey, str]]:
    """Count findings by place, and keep a readable label for each place separately."""
    anchors = {cause.id: cause for cause in report.root_causes}
    counts: Counter[CauseKey] = Counter()
    labels: dict[CauseKey, str] = {}
    for finding in findings:
        cause = anchors.get(finding.root_cause_id or "")
        if cause is None:
            continue
        key: CauseKey = (cause.anchor, path_of(finding.page_url))
        counts[key] += 1
        if cause.label and key not in labels:
            labels[key] = cause.label
    return counts, labels


def compare_reports(before: Report, after: Report) -> Comparison:
    reasons, notes = comparability(before, after)
    result = diff_findings(list(before.findings), list(after.findings))

    previous = {key_of(finding): finding for finding in before.findings}
    current = {key_of(finding): finding for finding in after.findings}
    closed = [previous[key] for key in previous.keys() - current.keys()]
    new = [current[key] for key in current.keys() - previous.keys()]
    remaining = [current[key] for key in previous.keys() & current.keys()]

    closed_counts, closed_labels = _cause_counter(closed, before)
    new_counts, new_labels = _cause_counter(new, after)
    remaining_counts, remaining_labels = _cause_counter(remaining, after)

    causes: list[CauseDelta] = []
    for key in sorted(set(closed_counts) | set(new_counts) | set(remaining_counts)):
        anchor, page = key
        causes.append(
            CauseDelta(
                anchor=anchor,
                page=page,
                label=(
                    new_labels.get(key)
                    or remaining_labels.get(key)
                    or closed_labels.get(key)
                    or anchor
                ),
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
        closed=list(result.closed),
        remaining=list(result.remaining),
        new=list(result.new),
        causes=causes,
    )


__all__ = [
    "CauseDelta",
    "Comparison",
    "comparability",
    "compare_reports",
    "pages_of",
]
