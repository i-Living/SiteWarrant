"""A host's runs over time: the numbers its stored reports recorded, and what changed.

The dashboard reads the report artifact, not the `findings` table: the chief layer merges
duplicates on its way into the report and leaves the rows it merged, so a SQL count per
category would be larger than the report it is meant to show. Tokens and calls come from the
audit row, because that is what the run spent — including an attempt that failed and was
retried, which no report records.

A run without a stored report keeps its place on the timeline with `null` numbers. The delta
between two runs carries `compare_reports`' own verdict: two runs of one host that share no
page are not a measurement of change, so such a point has no counts and names the reason
instead.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from app.audit import read_artifact
from app.compare import compare_reports
from app.core.models import Audit
from app.core.report import Report


class RunPoint(BaseModel):
    """One page audit on the timeline.

    Report-derived fields are `None` when the run wrote no report (failed, cancelled,
    still queued): a missing measurement is not a zero. `compared_to` names the previous
    run that did write one, because a failed run measured nothing to compare against.
    """

    audit_id: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    agent_version: str
    # What the worker recorded when the run failed; `None` for a run that finished.
    error: str | None
    # Whether the row names a stored report at all — an unreadable artifact still has one.
    has_report: bool
    pages_audited: int | None
    findings_total: int | None
    by_severity: dict[str, int] | None
    by_category: dict[str, int] | None
    scores: dict[str, float] | None
    duration_ms: int | None
    # Measured usage of the run; the audit row accumulates every attempt's calls.
    tokens_in: int
    tokens_out: int
    llm_calls: int
    # An estimate from the pinned price table; `None` when any model went unpriced.
    cost_estimate_usd: float | None
    compared_to: str | None = None
    # `None` when there is nothing to compare with; `False` when the pair is not a comparison.
    comparable: bool | None = None
    comparison_notes: list[str] = Field(default_factory=list)
    # Counts exist only for a comparable pair; on an incomparable one the reason does.
    new: int | None = None
    closed: int | None = None
    remaining: int | None = None


class SiteHistory(BaseModel):
    """The series a dashboard draws, oldest run first, plus what a reader must know."""

    host: str
    runs: list[RunPoint]
    notes: list[str] = Field(default_factory=list)


def load_report(report_key: str | None) -> Report | None:
    """The stored report behind a run, or `None` when it never wrote one.

    An unreadable artifact is treated like a missing one: the dashboard keeps the run on
    the timeline without numbers, and `build_history` counts it in its notes.
    """
    if report_key is None:
        return None
    try:
        return Report.model_validate_json(read_artifact(report_key))
    except (OSError, ValueError):
        return None


def read_reports(audits: Sequence[Audit]) -> list[tuple[Audit, Report | None]]:
    """Pair every run with its stored report, reading each artifact once."""
    return [(audit, load_report(audit.report_key)) for audit in audits]


def category_counts(report: Report) -> dict[str, int]:
    """Findings per category, as the report counts them (post-dedupe, one rule one finding)."""
    counts = Counter(finding.category for finding in report.findings)
    return dict(sorted(counts.items()))


def build_history(host: str, entries: Sequence[tuple[Audit, Report | None]]) -> SiteHistory:
    """The series for one host, comparing each run with the last one that has a report."""
    runs: list[RunPoint] = []
    previous: Report | None = None
    previous_id: str | None = None
    unreadable = 0

    for audit, report in entries:
        if audit.report_key is not None and report is None:
            unreadable += 1
        compared_to: str | None = None
        comparable: bool | None = None
        comparison_notes: list[str] = []
        new_count: int | None = None
        closed_count: int | None = None
        remaining_count: int | None = None
        if report is not None and previous is not None:
            comparison = compare_reports(previous, report)
            compared_to = previous_id
            comparable = comparison.comparable
            comparison_notes = [*comparison.reasons, *comparison.notes]
            # An incomparable pair has no measurement of change; hiding the counts is
            # the point of the verdict, not a formatting choice.
            if comparison.comparable:
                new_count = len(comparison.new)
                closed_count = len(comparison.closed)
                remaining_count = len(comparison.remaining)
        summary = report.summary if report is not None else None
        # The row carries what the audit spent, including a failed attempt. A run with no
        # model calls never writes a row total, but its report says 0.0 — an unknown price
        # is `None` and a run that made no calls is not unknown.
        cost = audit.cost_estimate_usd
        if cost is None and summary is not None:
            cost = summary.cost_estimate_usd
        runs.append(
            RunPoint(
                audit_id=str(audit.id),
                started_at=audit.started_at,
                finished_at=audit.finished_at,
                status=audit.status,
                agent_version=audit.agent_version,
                error=audit.error,
                has_report=audit.report_key is not None,
                pages_audited=None if summary is None else summary.pages_audited,
                findings_total=None if summary is None else summary.findings_total,
                by_severity=None if summary is None else summary.by_severity,
                by_category=None if report is None else category_counts(report),
                scores=None if summary is None else summary.scores,
                duration_ms=None if summary is None else summary.duration_ms,
                tokens_in=audit.tokens_in,
                tokens_out=audit.tokens_out,
                llm_calls=audit.llm_calls,
                cost_estimate_usd=cost,
                compared_to=compared_to,
                comparable=comparable,
                comparison_notes=comparison_notes,
                new=new_count,
                closed=closed_count,
                remaining=remaining_count,
            )
        )
        if report is not None:
            previous = report
            previous_id = str(audit.id)

    notes: list[str] = []
    if unreadable:
        notes.append(
            f"{unreadable} run(s) name a stored report that could not be read; "
            "they keep their place on the timeline without numbers"
        )
    return SiteHistory(host=host, runs=runs, notes=notes)
