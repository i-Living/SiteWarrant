import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, Numeric, delete, func, select, update
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import lifecycle
from app.core.models import (
    Audit,
    AuditSchedule,
    Finding,
    FindingEvidence,
    FindingFeedback,
    LlmCall,
    Observation,
    Page,
    Snapshot,
)
from app.core.models import RootCause as RootCauseRow
from app.core.report import RootCauseOut
from app.rules.engine import FindingDraft, NewObservation


async def create_audit(
    session: AsyncSession,
    *,
    site_url: str,
    agent_version: str,
    config: dict[str, Any],
    audit_id: uuid.UUID | None = None,
    status: str = lifecycle.RUNNING,
    owner_id: str | None = None,
    commit: bool = True,
) -> uuid.UUID:
    """Write the row a caller can already name — once.

    The API answers `202` with an id before anything runs, so it writes the row itself; the
    worker then runs the audit with that id and must not insert a second row. `ON CONFLICT DO
    NOTHING` makes the insert idempotent in both directions, including a retried delivery.

    `commit=False` is for a caller that writes more than one row and needs them together — the
    schedule loop advances `next_run_at` in the same transaction as the audit it just queued,
    or two workers could pick the same schedule and queue it twice.
    """
    audit_id = audit_id or uuid.uuid4()
    await session.execute(
        insert(Audit)
        .values(
            id=audit_id,
            site_url=site_url,
            status=status,
            stage=None,
            agent_version=agent_version,
            config=config,
            owner_id=owner_id,
        )
        .on_conflict_do_nothing(index_elements=[Audit.id])
    )
    if commit:
        await session.commit()
    return audit_id


async def save_page(
    session: AsyncSession,
    *,
    audit_id: uuid.UUID,
    url: str,
    key: str,
    status_code: int,
    render_mode: str,
) -> uuid.UUID:
    page = Page(
        audit_id=audit_id,
        url=url,
        page_key=key,
        status_code=status_code,
        render_mode=render_mode,
    )
    session.add(page)
    await session.flush()
    return page.id


async def save_snapshot(
    session: AsyncSession,
    *,
    page_id: uuid.UUID,
    viewport: str,
    html_key: str,
    dom_key: str | None = None,
    screenshot_key: str | None = None,
) -> None:
    session.add(
        Snapshot(
            page_id=page_id,
            viewport=viewport,
            html_key=html_key,
            dom_key=dom_key,
            screenshot_key=screenshot_key,
        )
    )


async def save_observations(
    session: AsyncSession,
    *,
    page_id: uuid.UUID,
    observations: Sequence[NewObservation],
) -> None:
    for item in observations:
        session.add(
            Observation(
                id=item.id,
                page_id=page_id,
                viewport=item.viewport,
                tool=item.tool,
                rule_ref=item.rule_ref,
                kind=item.kind,
                payload=item.payload,
            )
        )


async def save_findings(
    session: AsyncSession,
    *,
    audit_id: uuid.UUID,
    page_id: uuid.UUID,
    drafts: Sequence[FindingDraft],
) -> list[tuple[uuid.UUID, FindingDraft]]:
    stored: list[tuple[uuid.UUID, FindingDraft]] = []
    for draft in drafts:
        finding = Finding(
            audit_id=audit_id,
            page_id=page_id,
            rule_id=draft.rule_id,
            category=draft.category,
            severity=draft.severity,
            title=draft.title,
            summary=draft.summary,
            suggested_fix=draft.suggested_fix,
            impact_conversion=draft.impact_conversion,
            impact_seo=draft.impact_seo,
            impact_ux=draft.impact_ux,
            confidence=draft.confidence,
            basis=draft.basis,
            agent=draft.agent,
            subject=draft.subject,
        )
        session.add(finding)
        await session.flush()
        for evidence in draft.evidence:
            session.add(
                FindingEvidence(
                    finding_id=finding.id,
                    observation_id=uuid.UUID(evidence.observation_id),
                    kind=evidence.kind,
                    excerpt=evidence.excerpt,
                )
            )
        stored.append((finding.id, draft))
    return stored


async def finish_audit(
    session: AsyncSession,
    *,
    audit_id: uuid.UUID,
    status: str,
    pages_count: int,
    report_key: str | None,
    error: str | None = None,
    worker_id: str | None = None,
) -> bool:
    """Move the row to a terminal state, or refuse a move the life cycle does not have.

    Returns False when the row is already terminal in another state — a cancellation that
    arrived while the last stage was running wins, and the caller must not treat that as a
    failure of its own work.

    With a `worker_id` the write is fenced on the lease holder as well: a worker whose lease
    expired and whose row another worker has since claimed updates nothing and returns False.
    The condition has to name the worker, not just `running` — a reclaimed row is `running`
    again, under a new owner.
    """
    values = {
        "status": status,
        "stage": None,
        "worker_id": None,
        "lease_expires_at": None,
        "pages_count": pages_count,
        "report_key": report_key,
        "error": error,
        "finished_at": datetime.now(UTC),
    }
    if worker_id is None:
        audit = await session.get(Audit, audit_id)
        if audit is None or not lifecycle.can_transition(audit.status, status):
            return False
        for column, value in values.items():
            setattr(audit, column, value)
        return True
    if not lifecycle.can_transition(lifecycle.RUNNING, status):
        return False
    result = await session.execute(
        update(Audit)
        .where(
            Audit.id == audit_id,
            Audit.worker_id == worker_id,
            Audit.status == lifecycle.RUNNING,
        )
        .values(**values)
    )
    return bool(cast(CursorResult[Any], result).rowcount)


async def claim_audit(
    session: AsyncSession, *, worker_id: str, lease_s: int
) -> tuple[uuid.UUID, str] | None:
    """Take the oldest queued audit and hold it under a lease.

    `SKIP LOCKED` is what makes two workers safe: the second one walks past the row the first
    has locked instead of waiting for it and running it again.
    """
    candidate = (
        await session.execute(
            select(Audit)
            .where(Audit.status == lifecycle.QUEUED)
            .order_by(Audit.started_at, Audit.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if candidate is None:
        return None
    now = datetime.now(UTC)
    lifecycle.ensure_transition(candidate.status, lifecycle.RUNNING)
    candidate.status = lifecycle.RUNNING
    candidate.stage = "starting"
    candidate.worker_id = worker_id
    candidate.lease_expires_at = now + timedelta(seconds=lease_s)
    candidate.attempts += 1
    candidate.started_at = now
    await session.commit()
    return candidate.id, candidate.site_url


async def audit_owner(session: AsyncSession, audit_id: uuid.UUID) -> str | None:
    """Who holds the row right now: None when the row is gone or nobody holds it."""
    return (
        await session.execute(select(Audit.worker_id).where(Audit.id == audit_id))
    ).scalar_one_or_none()


async def renew_lease(
    session: AsyncSession, *, audit_id: uuid.UUID, worker_id: str, lease_s: int
) -> bool:
    """Say the worker is still alive. A row another worker took over is not renewed.

    One conditional `UPDATE`, not a read followed by a write: while recovery holds the row,
    a heartbeat that read the row first would block on the write and then stamp its lease onto
    a row recovery has requeued, or onto the next worker's claim. The condition is re-checked
    under the lock, so a lost row updates nothing and the caller stops.
    """
    result = await session.execute(
        update(Audit)
        .where(
            Audit.id == audit_id,
            Audit.worker_id == worker_id,
            Audit.status == lifecycle.RUNNING,
        )
        .values(lease_expires_at=datetime.now(UTC) + timedelta(seconds=lease_s))
    )
    await session.commit()
    return bool(cast(CursorResult[Any], result).rowcount)


async def set_stage(
    session: AsyncSession, *, audit_id: uuid.UUID, stage: str, worker_id: str | None = None
) -> bool:
    """Record the stage the worker has actually reached, not the one it hopes for.

    Returns False when the row is no longer this worker's: a stage write is the first thing a
    stale lease notices, so the caller stops there instead of finishing an audit somebody else
    owns.
    """
    if worker_id is not None:
        result = await session.execute(
            update(Audit)
            .where(
                Audit.id == audit_id,
                Audit.worker_id == worker_id,
                Audit.status == lifecycle.RUNNING,
            )
            .values(stage=stage)
        )
        await session.commit()
        return bool(cast(CursorResult[Any], result).rowcount)
    audit = await session.get(Audit, audit_id)
    if audit is None or audit.status != lifecycle.RUNNING:
        return False
    audit.stage = stage
    await session.commit()
    return True


async def requeue_expired(session: AsyncSession, *, max_attempts: int) -> tuple[int, int]:
    """Return audits whose worker vanished to the queue, and fail the ones out of attempts.

    This is the recovery a restart needs: a process that dies mid-audit stops renewing the
    lease, and the row is picked up again instead of sitting `running` forever.

    The rows stay locked (`FOR UPDATE SKIP LOCKED`) until the commit, so a heartbeat that lands
    between the select and the write cannot be discarded by a stale read: it waits for the lock
    and then finds the row already requeued, and answers False.
    """
    now = datetime.now(UTC)
    expired = (
        await session.execute(
            select(Audit)
            .where(
                Audit.status == lifecycle.RUNNING,
                Audit.lease_expires_at.is_not(None),
                Audit.lease_expires_at < now,
            )
            .with_for_update(skip_locked=True)
        )
    ).scalars()
    requeued = 0
    abandoned = 0
    for audit in expired:
        if audit.attempts < max_attempts:
            lifecycle.ensure_transition(audit.status, lifecycle.QUEUED)
            # The next attempt writes its own pages under the same audit id. The dead attempt's
            # facts would otherwise be served to the next run's agents through
            # `observation_index` and cited in its report, so they go with it. `llm_calls` stays:
            # those tokens were really spent, and deleting the record would hide the cost.
            await session.execute(delete(Page).where(Page.audit_id == audit.id))
            audit.status = lifecycle.QUEUED
            audit.stage = None
            audit.worker_id = None
            audit.lease_expires_at = None
            requeued += 1
        else:
            lifecycle.ensure_transition(audit.status, lifecycle.FAILED)
            audit.status = lifecycle.FAILED
            audit.stage = None
            audit.worker_id = None
            audit.lease_expires_at = None
            audit.finished_at = now
            audit.error = (
                f"the worker stopped renewing its lease {audit.attempts} time(s); "
                "the audit was not completed"
            )
            abandoned += 1
    await session.commit()
    return requeued, abandoned


async def request_cancel(session: AsyncSession, audit_id: uuid.UUID) -> Audit | None:
    """Stop a queued audit now, ask a running one to stop at its next stage boundary.

    A running audit is mid-browser; killing it would leave the row describing a stage nobody
    finished. The flag is checked between stages, and the worker writes `cancelled` itself.

    The row is locked for the branch: a claim that commits between this read and this write would
    otherwise turn a `queued` row into a `running` one while the cancel still wrote `cancelled`,
    and the worker running it would never learn it was asked to stop.
    """
    audit = (
        await session.execute(select(Audit).where(Audit.id == audit_id).with_for_update())
    ).scalar_one_or_none()
    if audit is None or lifecycle.is_terminal(audit.status):
        return audit
    if audit.status == lifecycle.QUEUED:
        lifecycle.ensure_transition(audit.status, lifecycle.CANCELLED)
        audit.status = lifecycle.CANCELLED
        audit.finished_at = datetime.now(UTC)
        audit.error = "cancelled before it started"
        audit.stage = None
    else:
        audit.cancel_requested = True
    await session.commit()
    return audit


async def cancel_requested(session: AsyncSession, audit_id: uuid.UUID) -> bool:
    audit = await session.get(Audit, audit_id)
    return audit is not None and audit.cancel_requested


async def get_audit(session: AsyncSession, audit_id: uuid.UUID) -> Audit | None:
    result = await session.execute(select(Audit).where(Audit.id == audit_id))
    return result.scalar_one_or_none()


async def list_audits(session: AsyncSession, *, limit: int) -> Sequence[Audit]:
    """Newest first: the progress page reads the same order the list is written in."""
    result = await session.execute(
        select(Audit).order_by(Audit.started_at.desc(), Audit.id.desc()).limit(limit)
    )
    return result.scalars().all()


async def latest_audit_per_url(session: AsyncSession) -> Sequence[Audit]:
    """One row per exact URL: the newest audit of it.

    The site views merge URL variants (trailing slash, query) in Python, so the number of
    rows they transfer follows pages, not runs.
    """
    result = await session.execute(
        select(Audit)
        .ext(distinct_on(Audit.site_url))
        .order_by(Audit.site_url, Audit.started_at.desc(), Audit.id.desc())
    )
    return result.scalars().all()


async def audit_counts_per_url(session: AsyncSession) -> Sequence[tuple[str, int]]:
    """Runs per exact URL, for the site rollups."""
    result = await session.execute(select(Audit.site_url, func.count()).group_by(Audit.site_url))
    return [(url, runs) for url, runs in result.all()]


async def save_llm_calls(
    session: AsyncSession,
    *,
    audit_id: uuid.UUID,
    run: Any,
    model: str,
    trace_id: str | None = None,
    price: Any = None,
) -> None:
    """One row per model call, from the per-call stats the runner kept."""
    for stat in run.calls:
        session.add(
            LlmCall(
                audit_id=audit_id,
                agent=run.name,
                model=model,
                tokens_in=stat.tokens_in,
                tokens_out=stat.tokens_out,
                latency_ms=stat.latency_ms,
                trace_id=trace_id,
                cost_estimate_usd=(
                    None if price is None else price.cost(stat.tokens_in, stat.tokens_out)
                ),
            )
        )


async def add_audit_usage(
    session: AsyncSession,
    *,
    audit_id: uuid.UUID,
    tokens_in: int,
    tokens_out: int,
    llm_calls: int,
    cost_estimate_usd: float | None = None,
) -> None:
    """Add one attempt's usage to the audit's totals, atomically.

    `+=` on an ORM attribute reads the row and writes the sum back, so an attempt that records its
    calls while the next attempt records its own can overwrite the other total. The increment is a
    SQL expression, evaluated by the database against the row it updates.
    """
    values: dict[str, Any] = {
        "tokens_in": Audit.tokens_in + tokens_in,
        "tokens_out": Audit.tokens_out + tokens_out,
        "llm_calls": Audit.llm_calls + llm_calls,
    }
    if cost_estimate_usd is not None:
        # `round(float, int)` does not exist in Postgres; the sum is cast to numeric for it.
        values["cost_estimate_usd"] = func.round(
            (func.coalesce(Audit.cost_estimate_usd, 0.0) + cost_estimate_usd).cast(Numeric(14, 6)),
            6,
        )
    await session.execute(update(Audit).where(Audit.id == audit_id).values(**values))


async def save_root_causes(
    session: AsyncSession,
    *,
    audit_id: uuid.UUID,
    page_id: uuid.UUID,
    causes: Sequence[RootCauseOut],
) -> dict[str, uuid.UUID]:
    """Store the deterministic clusters and return report id -> row id."""
    stored: dict[str, uuid.UUID] = {}
    for cause in causes:
        row = RootCauseRow(
            audit_id=audit_id,
            page_id=page_id,
            cause_kind=cause.kind,
            anchor=cause.anchor,
            summary=cause.summary,
            rationale=cause.rationale,
            severity=cause.severity,
            priority=cause.priority,
            categories=list(cause.categories),
        )
        session.add(row)
        await session.flush()
        stored[cause.id] = row.id
    return stored


async def assign_root_causes(session: AsyncSession, *, mapping: dict[str, uuid.UUID]) -> None:
    """Point stored findings at their cluster. Unknown ids are ignored, not invented."""
    for finding_id, cause_id in mapping.items():
        finding = await session.get(Finding, uuid.UUID(finding_id))
        if finding is not None:
            finding.root_cause_id = cause_id


async def find_recent_duplicate(
    session: AsyncSession,
    *,
    site_url: str,
    agents: Sequence[str],
    window_s: int,
    scope: str = "page",
) -> Audit | None:
    """An audit of the same URL, scope and agents, started inside the window.

    A double-clicked form and a retried request both describe one intention; a second run of
    the same page also costs another model call. `force` in the request body is how a caller
    says it wants a new one anyway. The scope is part of the identity: a page audit of a URL
    does not answer a request to walk its sitemap.
    """
    since = datetime.now(UTC) - timedelta(seconds=window_s)
    rows = (
        await session.execute(
            select(Audit)
            .where(Audit.site_url == site_url, Audit.started_at >= since)
            .order_by(Audit.started_at.desc())
            .limit(20)
        )
    ).scalars()
    wanted = list(agents)
    for audit in rows:
        # A failure is the caller's reason to try again, not a duplicate: answering with it would
        # hide the retry behind a `deduplicated: true`.
        if audit.status in (lifecycle.FAILED, lifecycle.CANCELLED):
            continue
        if list(audit.config.get("agents") or []) != wanted:
            continue
        if str(audit.config.get("scope") or "page") == scope:
            return audit
    return None


async def finding_exists(session: AsyncSession, finding_id: uuid.UUID) -> bool:
    return (await session.get(Finding, finding_id)) is not None


async def add_feedback(
    session: AsyncSession,
    *,
    finding_id: uuid.UUID,
    verdict: str,
    source: str,
    note: str | None,
) -> FindingFeedback:
    row = FindingFeedback(finding_id=finding_id, verdict=verdict, source=source, note=note)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def list_feedback(session: AsyncSession, finding_id: uuid.UUID) -> Sequence[FindingFeedback]:
    result = await session.execute(
        select(FindingFeedback)
        .where(FindingFeedback.finding_id == finding_id)
        .order_by(FindingFeedback.created_at, FindingFeedback.id)
    )
    return result.scalars().all()


async def findings_for_audit(session: AsyncSession, audit_id: uuid.UUID) -> Sequence[Finding]:
    """The stored finding rows of one audit, duplicates included.

    A label export asks which defects were reported on a page, and the chief layer's in-memory
    dedupe does not change the answer: a rule reported twice is still one label.
    """
    result = await session.execute(select(Finding).where(Finding.audit_id == audit_id))
    return result.scalars().all()


async def upsert_schedule(
    session: AsyncSession,
    *,
    site_url: str,
    every_minutes: int,
    agents: Sequence[str],
    owner_id: str | None,
    now: datetime | None = None,
) -> tuple[AuditSchedule, bool]:
    """One schedule per URL: a second POST edits the first instead of doubling the bill.

    Returns the row and whether it was created, so the API can answer 201 or 200 honestly.
    """
    existing = (
        await session.execute(select(AuditSchedule).where(AuditSchedule.site_url == site_url))
    ).scalar_one_or_none()
    if existing is None:
        schedule = AuditSchedule(
            site_url=site_url,
            every_minutes=every_minutes,
            agents=list(agents),
            owner_id=owner_id,
            enabled=True,
            # First run is one interval out: a schedule created now should not compete with the
            # audit the operator is presumably starting by hand.
            next_run_at=(now or datetime.now(UTC)) + timedelta(minutes=every_minutes),
        )
        session.add(schedule)
        try:
            await session.commit()
        except IntegrityError:
            # Two requests for one new URL: the unique constraint decides, and the loser edits
            # the row the winner just inserted instead of answering 500.
            await session.rollback()
            existing = (
                await session.execute(
                    select(AuditSchedule).where(AuditSchedule.site_url == site_url)
                )
            ).scalar_one()
            existing.every_minutes = every_minutes
            existing.agents = list(agents)
            existing.owner_id = owner_id
            await session.commit()
            await session.refresh(existing)
            return existing, False
        await session.refresh(schedule)
        return schedule, True
    existing.every_minutes = every_minutes
    existing.agents = list(agents)
    existing.owner_id = owner_id
    await session.commit()
    await session.refresh(existing)
    return existing, False


async def list_schedules(session: AsyncSession) -> Sequence[AuditSchedule]:
    result = await session.execute(select(AuditSchedule).order_by(AuditSchedule.site_url))
    return result.scalars().all()


async def get_schedule(session: AsyncSession, schedule_id: uuid.UUID) -> AuditSchedule | None:
    return await session.get(AuditSchedule, schedule_id)


async def set_schedule_enabled(
    session: AsyncSession, schedule_id: uuid.UUID, enabled: bool
) -> AuditSchedule | None:
    schedule = await session.get(AuditSchedule, schedule_id)
    if schedule is None:
        return None
    schedule.enabled = enabled
    if enabled:
        # Re-enabling waits one interval instead of firing the backlog immediately.
        schedule.next_run_at = datetime.now(UTC) + timedelta(minutes=schedule.every_minutes)
    await session.commit()
    return schedule


async def due_schedules(
    session: AsyncSession, *, limit: int, now: datetime | None = None
) -> Sequence[AuditSchedule]:
    """Schedules whose time has come, locked so two workers cannot both queue them."""
    moment = now or datetime.now(UTC)
    result = await session.execute(
        select(AuditSchedule)
        .where(AuditSchedule.enabled, AuditSchedule.next_run_at <= moment)
        .order_by(AuditSchedule.next_run_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return result.scalars().all()


async def in_flight_for_url(session: AsyncSession, site_url: str) -> bool:
    result = await session.execute(
        select(Audit.id)
        .where(Audit.site_url == site_url, Audit.status.in_(tuple(lifecycle.IN_FLIGHT)))
        .limit(1)
    )
    return result.scalar_one_or_none() is not None
