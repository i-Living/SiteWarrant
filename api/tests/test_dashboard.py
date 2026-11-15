"""The dashboard series: numbers from the report, nulls for what was never measured."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app import dashboard
from app.core.models import Audit
from app.core.report import EvidenceOut, FindingOut, ImpactOut, Report, build_report
from app.dashboard import build_history, history_window

START = datetime(2026, 11, 15, 10, 0, tzinfo=UTC)
SITE = "http://example.test/"


def finding(rule_id: str, category: str, severity: str = "major", page: str = "/") -> FindingOut:
    return FindingOut(
        id=f"{rule_id}-{page}",
        rule_id=rule_id,
        category=category,
        severity=severity,  # type: ignore[arg-type]
        title=f"{rule_id} title",
        summary="summary",
        suggested_fix="fix",
        impact=ImpactOut(conversion=0, seo=0, ux=0),
        confidence=1.0,
        agent="dom",
        page_url=f"http://example.test{page}",
        page_key=f"example.test{page}",
        evidence=[EvidenceOut(kind="dom", observation_id="obs-1")],
    )


def report(
    findings: list[FindingOut],
    *,
    pages: list[str],
    version: str = "sha256:aaa",
    duration_ms: int = 1200,
) -> Report:
    return build_report(
        audit_id=str(uuid.uuid4()),
        site=SITE,
        agent_version=version,
        status="completed",
        findings=findings,
        pages_audited=1,
        duration_ms=duration_ms,
        measured_categories={item.category for item in findings},
        observations_by_tool={},
        pages=pages,
    )


def audit(
    index: int,
    *,
    report_key: str | None,
    status: str = "completed",
    cost: float | None = 0.01,
) -> Audit:
    started = START + timedelta(minutes=index)
    return Audit(
        id=uuid.uuid4(),
        site_url=SITE,
        status=status,
        agent_version="sha256:aaa",
        report_key=report_key,
        pages_count=1 if report_key is not None else 0,
        started_at=started,
        finished_at=started,
        tokens_in=100 * index,
        tokens_out=10 * index,
        llm_calls=index,
        cost_estimate_usd=cost,
    )


def test_a_run_with_no_model_calls_costs_zero_and_an_unpriced_one_costs_nothing_known() -> None:
    free = audit(0, report_key="audits/a/report.json", cost=None)
    unpriced = audit(1, report_key="audits/b/report.json", cost=None)
    priced_report = report([], pages=["/"])
    unpriced_report = report([], pages=["/"]).model_copy(deep=True)
    unpriced_report.summary.cost_estimate_usd = None
    unpriced_report.summary.llm_calls = 1

    history = build_history(
        "example.test",
        [(free, priced_report), (unpriced, unpriced_report)],
    )

    # The report of a run that made no calls says 0.0; the row never wrote a total.
    assert priced_report.summary.llm_calls == 0
    assert history.runs[0].cost_estimate_usd == 0.0
    # An unpriced model is unknown, not free.
    assert history.runs[1].cost_estimate_usd is None


def test_a_run_without_a_report_keeps_its_place_without_numbers() -> None:
    failed = audit(0, report_key=None, status="failed", cost=None)
    finished = audit(1, report_key="audits/x/report.json")

    history = build_history(
        "example.test",
        [(failed, None), (finished, report([finding("SEO-TITLE", "seo")], pages=["/"]))],
    )

    first, second = history.runs
    assert first.status == "failed"
    assert first.findings_total is None
    assert first.by_category is None
    assert first.scores is None
    assert first.cost_estimate_usd is None
    # The failed run measured nothing, so it is not what the next one is compared with.
    assert second.compared_to is None
    assert second.comparable is None
    assert second.findings_total == 1


def test_the_next_report_is_compared_with_the_last_one_that_measured() -> None:
    first = audit(0, report_key="audits/a/report.json")
    failed = audit(1, report_key=None, status="failed")
    third = audit(2, report_key="audits/c/report.json")

    history = build_history(
        "example.test",
        [
            (first, report([], pages=["/"])),
            (failed, None),
            (third, report([finding("A11Y-LANG", "a11y")], pages=["/"])),
        ],
    )

    assert history.runs[1].compared_to is None
    assert history.runs[2].compared_to == str(first.id)
    assert history.runs[2].comparable is True


def test_a_category_count_comes_from_the_report() -> None:
    finished = audit(0, report_key="audits/a/report.json")
    stored = report(
        [
            finding("A11Y-LANG", "a11y"),
            finding("A11Y-IMG-ALT", "a11y"),
            finding("SEO-TITLE", "seo"),
        ],
        pages=["/"],
    )

    history = build_history("example.test", [(finished, stored)])

    assert history.runs[0].by_category == {"a11y": 2, "seo": 1}
    assert history.runs[0].findings_total == 3


def test_an_incomparable_pair_has_no_counts_and_names_the_reason() -> None:
    first = audit(0, report_key="audits/a/report.json")
    second = audit(1, report_key="audits/b/report.json")

    history = build_history(
        "example.test",
        [
            (first, report([finding("SEO-TITLE", "seo", page="/a")], pages=["/a"])),
            (second, report([finding("SEO-TITLE", "seo", page="/b")], pages=["/b"])),
        ],
    )

    point = history.runs[1]
    assert point.comparable is False
    assert point.new is None
    assert point.closed is None
    assert point.remaining is None
    assert any("share no page" in note for note in point.comparison_notes)


def test_a_comparable_pair_counts_closed_and_new_findings() -> None:
    first = audit(0, report_key="audits/a/report.json")
    second = audit(1, report_key="audits/b/report.json")

    history = build_history(
        "example.test",
        [
            (first, report([finding("SEO-TITLE", "seo")], pages=["/"])),
            (second, report([finding("A11Y-LANG", "a11y")], pages=["/"])),
        ],
    )

    point = history.runs[1]
    assert point.comparable is True
    assert point.closed == 1
    assert point.new == 1
    assert point.remaining == 0


def test_the_run_before_the_window_is_what_its_first_point_compares_with(
    monkeypatch,
) -> None:
    first = audit(0, report_key="audits/a/report.json")
    failed = audit(1, report_key=None, status="failed", cost=None)
    third = audit(2, report_key="audits/c/report.json")
    stored = {
        "audits/a/report.json": report([finding("SEO-TITLE", "seo")], pages=["/"]),
        "audits/c/report.json": report([finding("A11Y-LANG", "a11y")], pages=["/"]),
    }
    monkeypatch.setattr(dashboard, "load_report", stored.get)

    history = history_window("example.test", [first, failed, third], limit=2)

    # The window is the two runs asked for, not the context that made the delta possible.
    assert [run.audit_id for run in history.runs] == [str(failed.id), str(third.id)]
    assert history.runs[1].compared_to == str(first.id)
    assert history.runs[1].comparable is True
    assert history.runs[1].new == 1
    assert history.runs[1].closed == 1


def test_an_unreadable_predecessor_adds_no_note_about_a_run_outside_the_window(
    monkeypatch,
) -> None:
    lost = audit(0, report_key="audits/lost/report.json")
    finished = audit(1, report_key="audits/b/report.json")
    monkeypatch.setattr(
        dashboard,
        "load_report",
        {"audits/b/report.json": report([], pages=["/"])}.get,
    )

    history = history_window("example.test", [lost, finished], limit=1)

    assert [run.audit_id for run in history.runs] == [str(finished.id)]
    assert history.runs[0].compared_to is None
    assert history.notes == []
