"""A survey merges pages without inventing a cause that lives on none of them."""

import uuid

import pytest

from app.core.report import (
    AgentSummaryOut,
    EvidenceOut,
    FindingOut,
    ImpactOut,
    Report,
    RootCauseOut,
    SummaryOut,
)
from app.survey import merge_agents, merge_reports


def finding(*, page_key: str, rule_id: str = "SEO-H1", severity: str = "major") -> FindingOut:
    return FindingOut(
        id=str(uuid.uuid4()),
        rule_id=rule_id,
        category="seo",
        severity=severity,  # type: ignore[arg-type]
        title="Page has no h1",
        summary="measured",
        suggested_fix="add one",
        impact=ImpactOut(conversion=0, seo=2, ux=0),
        confidence=1.0,
        agent="rules",
        page_url=f"https://example.test/{page_key}",
        page_key=page_key,
        evidence=[EvidenceOut(kind="dom", observation_id=f"obs-{page_key}")],
    )


def cause(*, page_key: str, finding_ids: list[str]) -> RootCauseOut:
    return RootCauseOut(
        id=f"rc-{page_key}",
        kind="dom_anchor",
        anchor="header:nth-of-type(1)",
        label="header",
        categories=["a11y", "responsive"],
        summary="two findings share header",
        rationale="A11Y-LINK-NAME, LAYOUT-OCCLUSION",
        severity="major",
        priority=9.0,
        finding_ids=finding_ids,
    )


def page_report(
    *, page_key: str, findings: int, agents: list[AgentSummaryOut] | None = None
) -> Report:
    items = [finding(page_key=page_key) for _ in range(findings)]
    return Report(
        audit_id=str(uuid.uuid4()),
        site=f"https://example.test/{page_key}",
        agent_version="sha256:test",
        status="completed",
        generated_at="2026-11-13T00:00:00Z",  # type: ignore[arg-type]
        summary=SummaryOut(
            pages_audited=1,
            findings_total=findings,
            by_severity={"blocker": 0, "major": findings, "minor": 0, "info": 0},
            scores={"seo": 80.0},
            duration_ms=1000,
            observations_by_tool={"http": 8, "dom": 3},
            duplicates_removed=1,
            root_causes=1,
            agents=agents or [],
        ),
        findings=items,
        root_causes=[cause(page_key=page_key, finding_ids=[item.id for item in items])],
    )


def test_the_merged_report_counts_pages_findings_and_durations() -> None:
    merged = merge_reports(
        [page_report(page_key="a", findings=2), page_report(page_key="b", findings=3)],
        site="https://example.test/",
    )

    assert merged.summary.pages_audited == 2
    assert merged.summary.findings_total == 5
    assert merged.summary.duration_ms == 2000
    assert merged.summary.observations_by_tool == {"http": 16, "dom": 6}
    assert merged.summary.duplicates_removed == 2
    assert merged.summary.scores.keys() == {"seo"}
    assert merged.status == "completed"


def test_each_page_keeps_its_own_cause() -> None:
    """Two pages with a header each are two causes: the block is the same, the page is not."""
    merged = merge_reports(
        [page_report(page_key="a", findings=2), page_report(page_key="b", findings=2)],
        site="https://example.test/",
    )

    assert {cause.id for cause in merged.root_causes} == {"rc-a", "rc-b"}
    assert len(merged.root_causes) == 2
    assert {finding.root_cause_id for finding in merged.findings if finding.root_cause_id} <= {
        "rc-a",
        "rc-b",
    }


def test_a_failed_page_makes_the_survey_partial() -> None:
    merged = merge_reports(
        [page_report(page_key="a", findings=1)],
        site="https://example.test/",
        failures=[("https://example.test/b", "CaptureFailed: 500")],
    )

    assert merged.status == "partial"
    assert merged.summary.pages_audited == 1, "a page that failed is not counted as audited"


def test_an_empty_survey_is_an_error_not_an_empty_report() -> None:
    """A report of zero pages would read like a clean site."""
    with pytest.raises(ValueError):
        merge_reports([], site="https://example.test/")


def test_agent_totals_add_up_and_status_is_the_worst_case() -> None:
    ok = AgentSummaryOut(
        name="a11y",
        status="ok",
        model="m",
        cost_estimate_usd=0.01,
        findings=1,
        llm_calls=2,
        tokens_in=100,
        tokens_out=20,
        latency_ms=500,
    )
    failed = AgentSummaryOut(
        name="a11y",
        status="failed",
        model="m",
        cost_estimate_usd=0.02,
        findings=0,
        llm_calls=1,
        tokens_in=50,
        tokens_out=5,
        latency_ms=300,
        error="llm_error",
    )
    unmatched = AgentSummaryOut(name="seo", status="ok", model="unpriced", findings=3)

    merged = {
        agent.name: agent
        for agent in merge_agents(
            [
                page_report(page_key="a", findings=1, agents=[ok, unmatched]),
                page_report(page_key="b", findings=0, agents=[failed]),
            ]
        )
    }

    assert merged["a11y"].tokens_in == 150
    assert merged["a11y"].llm_calls == 3
    assert merged["a11y"].cost_estimate_usd == 0.03
    assert merged["a11y"].status == "failed", "one failed page means the agent covered no site"
    assert merged["a11y"].error == "llm_error"
    assert merged["seo"].findings == 3
