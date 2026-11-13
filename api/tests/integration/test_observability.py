"""What an audit can prove about itself: a trace, measured tokens, and a labelled cost."""

import json
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agents.orchestrator import observation_index, run_agents
from app.audit import artifact_path, run_audit
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.models import Audit, LlmCall
from app.pricing import BASIS, load_pricing

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


async def test_a_report_says_what_it_measured_and_what_it_guessed(cassette) -> None:
    cassette("a11y_valid.json")
    report = await run_audit(URL, allow_private=True, agents=["a11y"])

    summary = report.summary
    pricing = load_pricing()

    # Measured: the tokens the provider reported, and the calls that produced them.
    assert summary.llm_calls > 0
    assert summary.tokens_in > 0 and summary.tokens_out > 0
    assert summary.tokens_in == sum(agent.tokens_in for agent in summary.agents)
    assert summary.llm_calls == sum(agent.llm_calls for agent in summary.agents)

    # Estimated: priced with the version the audit recorded, and labelled as an estimate.
    assert summary.pricing["version"] == pricing.version
    assert summary.pricing["basis"] == BASIS
    assert summary.pricing["unpriced_models"] == []
    assert summary.cost_estimate_usd is not None and summary.cost_estimate_usd > 0
    agent = summary.agents[0]
    assert agent.model == get_settings().llm_model
    assert agent.cost_estimate_usd is not None
    expected = pricing.price_for(agent.model)
    assert expected is not None
    assert agent.cost_estimate_usd == pytest.approx(
        expected.cost(agent.tokens_in, agent.tokens_out), abs=1e-6
    )


async def test_the_trace_reaches_from_the_audit_down_to_the_model_call(cassette) -> None:
    # This cassette reads the facts through the tools before it submits, so the tree has depth.
    cassette("a11y_fabricated_then_fixed.json")
    report = await run_audit(URL, allow_private=True, agents=["a11y"])

    assert report.summary.trace_id
    spans = report.summary.spans
    # Deterministic work, one agent, its tool calls and its model calls: all on one trace.
    assert spans["audit"] == 1
    assert spans["page"] >= 1
    assert spans["agent"] == 1
    assert spans["llm.call"] >= 1

    path = artifact_path(f"audits/{report.audit_id}/trace.jsonl")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    records = [json.loads(line) for line in lines]
    assert {record["trace_id"] for record in records} == {report.summary.trace_id}
    by_name = {record["name"]: record for record in records}
    audit_span = by_name["audit"]
    page_span = next(record for record in records if record["name"] == "page")
    assert page_span["parent_span_id"] == audit_span["span_id"]
    agent_span = by_name["agent"]
    assert agent_span["parent_span_id"] == audit_span["span_id"]
    llm_span = by_name["llm.call"]
    assert llm_span["parent_span_id"] == agent_span["span_id"]
    assert llm_span["attributes"]["tokens_in"] > 0
    assert llm_span["attributes"]["cost_estimate_usd"] > 0


async def test_every_model_call_is_stored_with_its_trace_and_cost(cassette) -> None:
    cassette("a11y_valid.json")
    report = await run_audit(URL, allow_private=True, agents=["a11y"])

    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(LlmCall).where(LlmCall.audit_id == uuid.UUID(report.audit_id))
                )
            )
            .scalars()
            .all()
        )
    assert rows, "an agent that ran must leave one row per model call"
    for row in rows:
        assert row.trace_id == report.summary.trace_id
        assert row.cost_estimate_usd is not None and row.cost_estimate_usd > 0
        assert row.tokens_in > 0

    async with session_scope() as session:
        audit = await session.get(Audit, uuid.UUID(report.audit_id))
    assert audit is not None
    assert audit.config["pricing_version"] == load_pricing().version
    assert audit.cost_estimate_usd == pytest.approx(report.summary.cost_estimate_usd, abs=1e-6)


async def test_the_cost_ceiling_stops_an_agent_and_says_so(cassette) -> None:
    """A ceiling of zero is the honest test: no agent may run on a budget that is already gone."""
    cassette("a11y_valid.json")
    report = await run_audit(URL, allow_private=True, agents=["a11y"])
    settings = get_settings()

    orchestration = await run_agents(
        uuid.UUID(report.audit_id),
        names=["a11y", "seo"],
        settings=settings,
        cost_limit_usd=0.0,
    )
    runs = orchestration.runs
    assert [run.status for run in runs] == ["budget_exceeded", "budget_exceeded"]
    assert runs[0].cost_estimate_usd == 0.0
    assert "cost limit" in (runs[0].error or "")
    assert "did not run" in (runs[1].error or "")
    # The facts are untouched: a stopped agent loses findings, never observations.
    assert await observation_index(uuid.UUID(report.audit_id))
