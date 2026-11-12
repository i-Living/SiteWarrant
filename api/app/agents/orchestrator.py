import time
import uuid
from collections.abc import Sequence

from sqlalchemy import select

from app.agents.llm import CassetteClient, LlmClient, OpenAiCompatibleClient
from app.agents.models import AgentRun, ObservationFacts, OrchestrationResult
from app.agents.runner import run_agent
from app.agents.specs import spec_for
from app.core.config import Settings
from app.core.db import session_scope
from app.core.models import Observation, Page
from app.mcp.client import McpToolProvider
from app.rules import store


async def observation_index(audit_id: uuid.UUID) -> dict[str, ObservationFacts]:
    """Every fact of the audit, keyed by id: the same set the MCP server serves."""
    async with session_scope() as session:
        rows = await session.execute(
            select(Observation)
            .join(Page, Observation.page_id == Page.id)
            .where(Page.audit_id == audit_id)
        )
        return {
            str(row.id): ObservationFacts(
                tool=row.tool,
                kind=row.kind,
                rule_ref=row.rule_ref,
                viewport=row.viewport,
                payload=row.payload,
            )
            for row in rows.scalars()
        }


def first_observation_of(observations: dict[str, ObservationFacts], channel: str) -> str:
    """The first observation of a channel, or of a stored kind (``contrast_violation``)."""
    for observation_id, facts in observations.items():
        if channel in (facts.tool, facts.kind):
            return observation_id
    raise ValueError(f"this audit has no {channel} observation to cite")


def build_client(
    settings: Settings, agent: str, *, observations: dict[str, ObservationFacts] | None = None
) -> LlmClient:
    """One model for every agent, or a cassette when the run is a test.

    The provider decision is in docs/PLAN.md section 17: OpenCode Zen Go with
    deepseek-v4.1-flash, one provider, one model.
    """
    if settings.llm_cassette:
        facts = observations or {}
        return CassetteClient(
            settings.llm_cassette_path,
            model=settings.llm_model,
            resolve=lambda channel: first_observation_of(facts, channel),
        )
    return OpenAiCompatibleClient(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or None,
        session_id=f"sitewarrant-{agent}-{uuid.uuid4()}",
        timeout_s=settings.llm_timeout_s,
    )


def describe_error(error: BaseException) -> str:
    """Flatten an exception group, which is how anyio reports a failed subprocess."""
    if isinstance(error, BaseExceptionGroup) and error.exceptions:
        return describe_error(error.exceptions[0])
    return f"{type(error).__name__}: {error}"[:500]


async def run_agents(
    audit_id: uuid.UUID, *, names: Sequence[str], settings: Settings
) -> OrchestrationResult:
    """Run the selected agents against the stored facts and collect their candidates.

    An agent that fails is recorded and the audit continues: a report that silently dropped a
    failed agent would look complete when it is not, which is why the result carries the
    partial flag.
    """
    observations = await observation_index(audit_id)
    async with session_scope() as session:
        await store.ensure_indexed(session)

    runs: list[AgentRun] = []
    for name in names:
        started = time.monotonic()
        try:
            # The client is built inside the boundary too: a broken cassette or a missing key
            # is this agent's failure, not a reason to lose the audit's deterministic findings.
            spec = spec_for(name)
            llm = build_client(settings, name, observations=observations)
            async with McpToolProvider(str(audit_id)) as tools:
                run = await run_agent(spec, llm=llm, tools=tools, observations=observations)
        except Exception as error:
            run = AgentRun(
                name=name,
                status="failed",
                error=describe_error(error),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        runs.append(run)

    await _record_calls(audit_id, runs, settings.llm_model)
    return OrchestrationResult(runs=runs)


async def _record_calls(audit_id: uuid.UUID, runs: Sequence[AgentRun], model: str) -> None:
    from app.storage import repo

    async with session_scope() as session:
        for run in runs:
            await repo.save_llm_calls(session, audit_id=audit_id, run=run, model=model)
        await repo.add_audit_usage(
            session,
            audit_id=audit_id,
            tokens_in=sum(run.tokens_in for run in runs),
            tokens_out=sum(run.tokens_out for run in runs),
            llm_calls=sum(run.llm_calls for run in runs),
        )
        await session.commit()
