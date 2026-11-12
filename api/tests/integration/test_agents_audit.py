import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agents.orchestrator import observation_index
from app.audit import run_audit
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.models import Audit, LlmCall, Observation, Page

pytestmark = pytest.mark.integration

URL = "http://localhost:8081/"
CASSETTES = Path(__file__).resolve().parents[2] / "tests/agents/cassettes"


@pytest.fixture
def cassette(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], None]]:
    def use(name: str) -> None:
        monkeypatch.setenv("SITEWARRANT_LLM_CASSETTE", str(CASSETTES / name))
        get_settings.cache_clear()

    yield use
    monkeypatch.delenv("SITEWARRANT_LLM_CASSETTE", raising=False)
    get_settings.cache_clear()


async def stored_audit(audit_id: str) -> Audit:
    async with session_scope() as session:
        audit = await session.get(Audit, uuid.UUID(audit_id))
        assert audit is not None
        return audit


async def observation_ids(audit_id: str) -> set[str]:
    async with session_scope() as session:
        rows = await session.execute(
            select(Observation)
            .join(Page, Observation.page_id == Page.id)
            .where(Page.audit_id == uuid.UUID(audit_id))
        )
        return {str(row.id) for row in rows.scalars()}


async def test_an_agent_finding_cites_a_real_observation_and_a_criterion(cassette) -> None:
    cassette("a11y_valid.json")
    report = await run_audit(URL, allow_private=True, agents=["a11y"])

    agent_findings = [finding for finding in report.findings if finding.agent == "a11y"]
    assert len(agent_findings) == 1
    finding = agent_findings[0]
    assert finding.rule_id == "A11Y-TEXT-CONTRAST-ALPHA"
    assert finding.criterion == "WCAG-1.4.3"
    assert finding.criterion_title == "Contrast (Minimum)"
    assert finding.evidence, "an agent finding without evidence must never be stored"
    cited = {item.observation_id for item in finding.evidence}
    assert cited <= await observation_ids(report.audit_id)

    assert report.status == "completed"
    summary = report.summary.agents[0]
    assert (summary.name, summary.status, summary.findings) == ("a11y", "ok", 1)
    assert summary.tokens_in == 2100 and summary.tokens_out == 210

    audit = await stored_audit(report.audit_id)
    assert audit.tokens_in == 2100
    assert audit.llm_calls == 1
    async with session_scope() as session:
        calls = await session.execute(select(LlmCall).where(LlmCall.audit_id == audit.id))
        rows = list(calls.scalars())
    assert len(rows) == 1 and rows[0].agent == "a11y" and rows[0].model == "deepseek-v4.1-flash"


async def test_the_deterministic_layer_still_runs_alongside_the_agents(cassette) -> None:
    cassette("a11y_valid.json")
    report = await run_audit(URL, allow_private=True, agents=["a11y"])

    deterministic = [finding for finding in report.findings if finding.agent == "rules"]
    assert len(deterministic) == 9
    assert report.summary.by_severity["blocker"] == 2


async def test_a_fabricated_citation_never_reaches_the_report(cassette) -> None:
    """The acceptance test for P3, end to end: invented evidence is rejected and the agent
    gets one more chance with the real observation."""
    cassette("a11y_fabricated_then_fixed.json")
    report = await run_audit(URL, allow_private=True, agents=["a11y"])

    agent_findings = [finding for finding in report.findings if finding.agent == "a11y"]
    assert len(agent_findings) == 1
    cited = {item.observation_id for item in agent_findings[0].evidence}
    assert cited <= await observation_ids(report.audit_id)
    assert "00000000-0000-0000-0000-000000000000" not in cited

    summary = report.summary.agents[0]
    assert summary.status == "ok"
    assert summary.rejected == 1
    assert summary.llm_calls == 2


async def test_a_failed_agent_makes_the_report_partial(cassette) -> None:
    cassette("failed.json")
    report = await run_audit(URL, allow_private=True, agents=["a11y"])

    assert report.status == "partial"
    summary = report.summary.agents[0]
    assert summary.status == "llm_error"
    assert summary.error is not None and "cassette" in summary.error
    # The deterministic findings are still there: one agent failing is not a failed audit.
    assert len([finding for finding in report.findings if finding.agent == "rules"]) == 9

    audit = await stored_audit(report.audit_id)
    assert audit.status == "partial"


async def test_the_agent_can_reach_the_facts_over_mcp(cassette) -> None:
    """The prompt digest is abbreviated; the tools are how the agent gets the whole payload."""
    cassette("a11y_valid.json")
    report = await run_audit(URL, allow_private=True, agents=["a11y"])

    index = await observation_index(uuid.UUID(report.audit_id))
    assert any(facts.tool == "contrast" for facts in index.values())
    assert any(facts.tool == "performance" for facts in index.values())


async def test_an_unknown_agent_name_fails_before_anything_is_written(cassette) -> None:
    """An unknown name must not leave a failed audit with committed facts and no page count."""
    with pytest.raises(ValueError, match="unknown agent"):
        await run_audit(URL, allow_private=True, agents=["nope"])


async def test_a_broken_cassette_is_one_failed_agent_not_a_failed_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Client construction sits inside the per-agent boundary, so the audit still reports."""
    broken = CASSETTES / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    try:
        monkeypatch.setenv("SITEWARRANT_LLM_CASSETTE", str(broken))
        get_settings.cache_clear()
        report = await run_audit(URL, allow_private=True, agents=["a11y"])
    finally:
        broken.unlink(missing_ok=True)
        monkeypatch.delenv("SITEWARRANT_LLM_CASSETTE", raising=False)
        get_settings.cache_clear()

    assert report.status == "partial"
    assert report.summary.agents[0].status == "failed"
    assert report.summary.findings_total >= 9


async def test_a_failure_before_the_facts_commit_records_no_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing was persisted, so the failed audit must not claim a page."""

    async def failing_capture(*args: object, **kwargs: object) -> object:
        raise RuntimeError("capture exploded")

    monkeypatch.setattr("app.audit.capture_page", failing_capture)
    with pytest.raises(RuntimeError, match="capture exploded"):
        await run_audit(URL, allow_private=True)

    async with session_scope() as session:
        audit = (
            await session.execute(select(Audit).order_by(Audit.started_at.desc()).limit(1))
        ).scalar_one()
        assert audit.status == "failed"
        assert audit.pages_count == 0


async def test_a_failure_after_the_facts_commit_records_the_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The facts are in the database; a count of zero would describe a state that is not there."""

    async def failing_agents(*args: object, **kwargs: object) -> object:
        raise RuntimeError("agents exploded")

    monkeypatch.setattr("app.audit.run_agents", failing_agents)
    with pytest.raises(RuntimeError, match="agents exploded"):
        await run_audit(URL, allow_private=True, agents=["a11y"])

    async with session_scope() as session:
        audit = (
            await session.execute(select(Audit).order_by(Audit.started_at.desc()).limit(1))
        ).scalar_one()
        assert audit.status == "failed"
        assert audit.pages_count == 1
