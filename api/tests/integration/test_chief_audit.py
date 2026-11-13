"""The P4 acceptance: the fixture's banner is one cause, not a pile of unrelated findings."""

import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agents.models import LlmCallStat
from app.audit import run_audit
from app.chief.narrate import NarrationCall
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.models import Finding, LlmCall, RootCause

pytestmark = pytest.mark.integration

URL = "http://localhost:8081/"
CASSETTES = Path(__file__).resolve().parents[2] / "tests/agents/cassettes"


@pytest.fixture
def cassette(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], None]]:
    """An agent run needs a recorded conversation; narration is stubbed per test."""

    def use(name: str) -> None:
        monkeypatch.setenv("SITEWARRANT_LLM_CASSETTE", str(CASSETTES / name))
        get_settings.cache_clear()

    yield use
    monkeypatch.delenv("SITEWARRANT_LLM_CASSETTE", raising=False)
    get_settings.cache_clear()


async def test_the_banner_is_one_root_cause_with_symptoms_from_two_categories() -> None:
    report = await run_audit(URL, allow_private=True)

    assert report.summary.root_causes == 1
    cause = report.root_causes[0]
    assert cause.anchor == "header:nth-of-type(1)"
    assert cause.label == "header"
    assert len(cause.categories) >= 2, cause.categories
    assert len(cause.finding_ids) >= 2
    assert {"responsive", "a11y"} <= set(cause.categories)

    grouped = [finding for finding in report.findings if finding.root_cause_id == cause.id]
    assert {finding.rule_id for finding in grouped} == {"LAYOUT-OCCLUSION", "A11Y-LINK-NAME"}
    # The banner covers five links, and each covered target is its own finding: collapsing them
    # into one would hide four defects behind the first one's summary.
    covered = [finding for finding in grouped if finding.rule_id == "LAYOUT-OCCLUSION"]
    assert len(covered) == 5
    assert len({finding.subject for finding in covered}) == 5
    assert all(finding.priority > 0 for finding in report.findings)
    assert report.summary.duplicate_rate == 0.0


async def test_the_cluster_is_persisted_with_its_findings() -> None:
    report = await run_audit(URL, allow_private=True)

    async with session_scope() as session:
        causes = (
            (
                await session.execute(
                    select(RootCause).where(RootCause.audit_id == uuid.UUID(report.audit_id))
                )
            )
            .scalars()
            .all()
        )
        assert len(causes) == 1
        rows = (
            (await session.execute(select(Finding).where(Finding.root_cause_id == causes[0].id)))
            .scalars()
            .all()
        )
        assert len(rows) == len(report.root_causes[0].finding_ids)
        assert causes[0].anchor == "header:nth-of-type(1)"
        assert causes[0].priority > 0


async def test_a_page_level_defect_is_not_clustered() -> None:
    """An empty title is everywhere and therefore nowhere: no anchor, no cause."""
    report = await run_audit(URL, allow_private=True)
    titles = [finding for finding in report.findings if finding.rule_id == "SEO-TITLE"]
    assert titles
    assert titles[0].root_cause_id is None


async def test_the_narration_reaches_the_report_and_the_call_log(
    cassette: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The prose is stored with the cause and priced with the audit, next to the agent calls."""

    async def explained(causes, findings, *, settings, trace, audit_id):
        assert causes, "the stub is only called when there is a cluster"
        return NarrationCall(
            causes=[
                cause.model_copy(
                    update={
                        "summary": "The header hides the menu at 390 px.",
                        "rationale": "One fix in the header closes the labelled and covered links.",
                    }
                )
                for cause in causes
            ],
            status="ok",
            accepted=len(causes),
            tokens_in=900,
            tokens_out=120,
            llm_calls=1,
            latency_ms=400,
            calls=[LlmCallStat(tokens_in=900, tokens_out=120, latency_ms=400)],
        )

    monkeypatch.setattr("app.audit.explain_causes", explained)
    cassette("a11y_valid.json")
    report = await run_audit(URL, allow_private=True, agents=["a11y"])

    assert report.root_causes
    assert report.root_causes[0].summary == "The header hides the menu at 390 px."
    chief = next(agent for agent in report.summary.agents if agent.name == "chief")
    assert chief.status == "ok"
    assert (chief.tokens_in, chief.tokens_out, chief.llm_calls) == (900, 120, 1)
    assert chief.cost_estimate_usd is not None, "a priced model yields an estimate"
    # The chief's tokens are part of the audit total, not a separate ledger.
    assert report.summary.tokens_in >= 900
    assert report.summary.llm_calls >= 1

    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(LlmCall).where(
                        LlmCall.audit_id == uuid.UUID(report.audit_id),
                        LlmCall.agent == "chief",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].tokens_in == 900
    assert rows[0].cost_estimate_usd is not None


async def test_a_cassette_keeps_the_narration_off(cassette: Callable[[str], None]) -> None:
    """A recorded conversation has no narration in it, so the measured sentence stays."""
    cassette("a11y_valid.json")
    report = await run_audit(URL, allow_private=True, agents=["a11y"])

    chief_rows = [agent for agent in report.summary.agents if agent.name == "chief"]
    assert chief_rows == []
    assert "findings in" in report.root_causes[0].summary
    assert report.root_causes[0].rationale.startswith("A11Y-")
