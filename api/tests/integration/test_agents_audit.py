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
