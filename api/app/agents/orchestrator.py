import time
import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy import select

from app.agents.llm import CassetteClient, LlmClient, OpenAiCompatibleClient
from app.agents.models import AgentRun, ObservationFacts, OrchestrationResult
from app.agents.runner import run_agent
from app.agents.specs import spec_for
from app.agents.traced import CostLimitExceeded, TracedLlm, TracedTools
from app.core.config import Settings
from app.core.db import session_scope
from app.core.models import Observation, Page
from app.mcp.client import McpToolProvider
from app.pricing import Price, pricing
from app.rules import store
from app.telemetry import Tracer


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


def _cost_limit_in(error: BaseException) -> CostLimitExceeded | None:
    """Find the cost stop inside an exception group, if that is what happened."""
    if isinstance(error, CostLimitExceeded):
        return error
    if isinstance(error, BaseExceptionGroup):
        for nested in error.exceptions:
            found = _cost_limit_in(nested)
            if found is not None:
                return found
    return None


def describe_error(error: BaseException) -> str:
    """Flatten an exception group, which is how anyio reports a failed subprocess."""
    if isinstance(error, BaseExceptionGroup) and error.exceptions:
        return describe_error(error.exceptions[0])
    return f"{type(error).__name__}: {error}"[:500]


async def run_agents(
    audit_id: uuid.UUID,
    *,
    names: Sequence[str],
    settings: Settings,
    tracer: Tracer | None = None,
    cost_limit_usd: float | None = None,
) -> OrchestrationResult:
    """Run the selected agents against the stored facts and collect their candidates.

    An agent that fails is recorded and the audit continues: a report that silently dropped a
    failed agent would look complete when it is not, which is why the result carries the
    partial flag.
    """
    observations = await observation_index(audit_id)
    async with session_scope() as session:
        await store.ensure_indexed(session)

    trace = tracer or Tracer()
    price = pricing().price_for(settings.llm_model)
    limit = settings.audit_cost_limit_usd if cost_limit_usd is None else cost_limit_usd
    spent_usd = 0.0
    stopped_at: str | None = None
    runs: list[AgentRun] = []
    for name in names:
        if stopped_at is not None:
            # Never started, and the report says so: a skipped agent is not a clean page.
            runs.append(
                AgentRun(
                    name=name,
                    status="budget_exceeded",
                    model=settings.llm_model,
                    error=f"audit cost limit reached after {stopped_at}; this agent did not run",
                )
            )
            continue
        started = time.monotonic()
        try:
            with trace.span("agent", agent=name):
                run = await _run_one(
                    name,
                    audit_id=audit_id,
                    settings=settings,
                    observations=observations,
                    tracer=trace,
                    price=price,
                    remaining_usd=None if limit is None else max(limit - spent_usd, 0.0),
                )
        except Exception as error:
            # anyio reports a failure from a subprocess as a group: the ceiling is only visible
            # once the group is opened, and "failed" would hide why the agent stopped.
            limit_error = _cost_limit_in(error)
            if limit_error is not None:
                stopped_at = name
                run = AgentRun(
                    name=name,
                    status="budget_exceeded",
                    model=settings.llm_model,
                    cost_estimate_usd=limit_error.spent_usd if price is not None else None,
                    error=describe_error(limit_error),
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                spent_usd = round(spent_usd + (run.cost_estimate_usd or 0.0), 6)
                runs.append(run)
                continue
            # A broken cassette or a missing key is this agent's failure, not a reason to lose
            # the audit's deterministic findings.
            run = AgentRun(
                name=name,
                status="failed",
                model=settings.llm_model,
                error=describe_error(error),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        spent_usd = round(spent_usd + (run.cost_estimate_usd or 0.0), 6)
        runs.append(run)

    await _record_calls(audit_id, runs, settings.llm_model, trace.trace_id)
    return OrchestrationResult(runs=runs)


async def _run_one(
    name: str,
    *,
    audit_id: uuid.UUID,
    settings: Settings,
    observations: Mapping[str, ObservationFacts],
    tracer: Tracer,
    price: Price | None,
    remaining_usd: float | None,
) -> AgentRun:
    """One agent, with its model calls and tool calls on the trace and its cost counted."""
    spec = spec_for(name)
    llm = TracedLlm(
        build_client(settings, name, observations=dict(observations)),
        tracer=tracer,
        agent=name,
        price=price,
        cost_limit_usd=remaining_usd,
    )
    async with McpToolProvider(str(audit_id)) as tools:
        run = await run_agent(
            spec,
            llm=llm,
            tools=TracedTools(tools, tracer=tracer, agent=name),
            observations=observations,
        )
    run.model = llm.model
    # An unpriced model leaves the cost absent: the tokens are still measured.
    run.cost_estimate_usd = round(llm.spent_usd, 6) if price is not None else None
    return run


async def _record_calls(
    audit_id: uuid.UUID, runs: Sequence[AgentRun], model: str, trace_id: str | None = None
) -> None:
    from app.pricing import pricing
    from app.storage import repo

    price = pricing().price_for(model)
    async with session_scope() as session:
        for run in runs:
            await repo.save_llm_calls(
                session, audit_id=audit_id, run=run, model=model, trace_id=trace_id, price=price
            )
        await repo.add_audit_usage(
            session,
            audit_id=audit_id,
            tokens_in=sum(run.tokens_in for run in runs),
            tokens_out=sum(run.tokens_out for run in runs),
            llm_calls=sum(run.llm_calls for run in runs),
            cost_estimate_usd=(
                None
                if price is None
                else round(sum(run.cost_estimate_usd or 0.0 for run in runs), 6)
            ),
        )
        await session.commit()
