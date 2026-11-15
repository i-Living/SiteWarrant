"""Run queued audits outside the API process.

The queue is the `audits` table: a submitted audit is a row in `queued`, and a worker claims it
with `FOR UPDATE SKIP LOCKED` and holds it under a lease. Three properties follow from that and
are the reason the row exists at all:

- a restart loses the run, not the task — an unrenewed lease puts the row back in the queue;
- two workers cannot run one audit, because the second walks past the locked row;
- a cancelled audit stops at a stage boundary and says so, instead of disappearing.

The worker is a separate process (`sitewarrant-worker`). Nothing in the API executes an audit.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict

from app import lifecycle
from app.audit import (
    AuditCancelled,
    LeaseLost,
    audit_config,
    current_agent_version,
    run_audit,
)
from app.core.config import Settings, get_settings
from app.core.db import session_scope
from app.storage import repo

logger = logging.getLogger(__name__)

# A due schedule whose page is already being audited waits this long before it looks again: the
# in-flight run is the answer to the schedule's own question, and a second browser would only
# duplicate the bill.
SCHEDULE_RETRY_S = 60

# The loop backs off on a database error and never exits on one: nothing restarts this process,
# and a queue nobody is polling looks exactly like a queue with no work. The floor is separate from
# `poll_s`: an operator who sets a zero poll interval still must not turn an outage into a hot loop.
BACKOFF_MIN_S = 1.0
BACKOFF_MAX_S = 30.0


def error_pause(pause: float) -> float:
    """The wait after a failed loop pass: always positive, never longer than the ceiling."""
    return min(max(pause * 2, BACKOFF_MIN_S), BACKOFF_MAX_S)


class WorkerContext(BaseModel):
    """Who is working, for how long the lease lasts, and how often to look for work."""

    model_config = ConfigDict(frozen=True)

    worker_id: str
    lease_s: int
    poll_s: float
    max_attempts: int


def context_for(settings: Settings) -> WorkerContext:
    return WorkerContext(
        worker_id=settings.worker_name,
        lease_s=settings.worker_lease_s,
        poll_s=settings.worker_poll_s,
        max_attempts=settings.worker_max_attempts,
    )


async def recover(*, settings: Settings) -> tuple[int, int]:
    """Re-queue audits whose worker vanished; fail the ones that ran out of attempts."""
    async with session_scope() as session:
        return await repo.requeue_expired(session, max_attempts=settings.worker_max_attempts)


async def run_due_schedules(*, settings: Settings) -> int:
    """Queue the audits whose schedule is due, and advance the schedule in the same transaction.

    One transaction is what makes it safe: the schedule rows are locked (`SKIP LOCKED`), the audit
    rows and the new `next_run_at` commit together, so a second worker either sees the advanced
    time or skips the locked row — it never queues the same schedule twice.
    """
    moment = datetime.now(UTC)
    queued = 0
    async with session_scope() as session:
        due = await repo.due_schedules(session, limit=settings.worker_schedule_batch, now=moment)
        for schedule in due:
            if await repo.in_flight_for_url(session, schedule.site_url):
                schedule.next_run_at = moment + timedelta(seconds=SCHEDULE_RETRY_S)
                continue
            audit_id = await repo.create_audit(
                session,
                site_url=schedule.site_url,
                agent_version=current_agent_version(settings),
                config=audit_config(settings, agents=schedule.agents, ignore_robots=False),
                status=lifecycle.QUEUED,
                owner_id=schedule.owner_id or settings.owner_id,
                commit=False,
            )
            schedule.last_audit_id = audit_id
            schedule.next_run_at = moment + timedelta(minutes=schedule.every_minutes)
            queued += 1
        await session.commit()
    return queued


async def run_once(context: WorkerContext) -> bool:
    """Claim and run one audit. False means the queue was empty."""
    async with session_scope() as session:
        claimed = await repo.claim_audit(
            session, worker_id=context.worker_id, lease_s=context.lease_s
        )
    if claimed is None:
        return False
    audit_id, url = claimed
    # The row was written by whoever queued it: its agent list is the audit's, not the worker's
    # default, and the attempt decides which artifact directory this run may write.
    async with session_scope() as session:
        audit = await repo.get_audit(session, audit_id)
        agents = tuple(str(name) for name in (audit.config.get("agents") or [])) if audit else ()
        attempt = audit.attempts if audit else None
    await execute(audit_id, url, agents=agents, attempt=attempt, context=context)
    return True


async def execute(
    audit_id: uuid.UUID,
    url: str,
    *,
    context: WorkerContext,
    agents: tuple[str, ...] = (),
    attempt: int | None = None,
) -> None:
    """Run one claimed audit, renewing the lease while it works.

    A failure is the audit's, never the worker's: `audit_page` has already written the reason on
    the row, and the loop has to keep going or one broken URL would stop the queue.

    Losing the lease is different from failing: the row belongs to another worker now, so this
    run stops at the next stage boundary and writes nothing else. The fence lives in storage —
    `set_stage` and `finish_audit` are conditional on the worker id — and this loop only has to
    stop early instead of racing.
    """
    lease_lost = asyncio.Event()

    async def lost() -> LeaseLost:
        return LeaseLost(f"{audit_id} is no longer leased to {context.worker_id}")

    async def progress(stage: str) -> None:
        async with session_scope() as session:
            mine = await repo.set_stage(
                session, audit_id=audit_id, stage=stage, worker_id=context.worker_id
            )
        if not mine:
            raise await lost()

    async def cancelled() -> bool:
        if lease_lost.is_set():
            raise await lost()
        async with session_scope() as session:
            return await repo.cancel_requested(session, audit_id)

    heartbeat = asyncio.create_task(
        _heartbeat(audit_id, lease_lost=lease_lost, context=context), name=f"lease-{audit_id}"
    )
    try:
        await run_audit(
            url,
            agents=agents,
            audit_id=audit_id,
            progress=progress,
            cancelled=cancelled,
            worker_id=context.worker_id,
            attempt=attempt,
        )
    except AuditCancelled:
        logger.info("audit %s was cancelled", audit_id)
    except LeaseLost:
        logger.warning("audit %s was reclaimed by another worker; this run stopped", audit_id)
    except Exception:
        logger.exception("audit %s failed", audit_id)
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)


async def _renew_once(audit_id: uuid.UUID, context: WorkerContext) -> bool:
    """One renewal in its own task and its own session: it closes what it opened."""
    async with session_scope() as session:
        return await repo.renew_lease(
            session,
            audit_id=audit_id,
            worker_id=context.worker_id,
            lease_s=context.lease_s,
        )


def _renewal_finished(task: asyncio.Task[bool]) -> None:
    """A renewal nobody waits for any more must not leave an unretrieved exception."""
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.warning("abandoned lease renewal failed", exc_info=error)


async def _heartbeat(
    audit_id: uuid.UUID, *, lease_lost: asyncio.Event, context: WorkerContext
) -> None:
    """Keep the lease alive while the audit runs; stop when another worker owns the row.

    Every wait and the renewal itself are bounded by what is left of the lease. A renewal that is
    still blocked when the lease runs out has to be abandoned, not awaited: the other worker may
    already hold the row, and a success that lands afterwards would reset the deadline and hide it.
    """
    interval = max(1.0, context.lease_s / 3)
    deadline = time.monotonic() + context.lease_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            lease_lost.set()
            return
        # The sleep is bounded by the budget: a short lease, or a stalled loop, cannot carry the
        # heartbeat past the deadline and renew afterwards.
        await asyncio.sleep(min(interval, remaining))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            lease_lost.set()
            return
        # The renewal runs as its own task so the deadline does not depend on it finishing its
        # cancellation: `wait_for` would await the cancelled call, and closing a stalled session
        # can take as long as the statement that stalled it.
        renewal = asyncio.create_task(_renew_once(audit_id, context))
        renewal.add_done_callback(_renewal_finished)
        done, _pending = await asyncio.wait({renewal}, timeout=remaining)
        if not done:
            renewal.cancel()
            logger.warning("lease renewal for %s outlived the lease", audit_id)
            lease_lost.set()
            return
        try:
            renewed = renewal.result()
        except Exception:
            logger.warning("lease renewal for %s failed", audit_id, exc_info=True)
            if time.monotonic() >= deadline:
                lease_lost.set()
                return
            continue
        if not renewed:
            # The run cannot be cancelled in the middle of a stage, but it can be told to stop
            # at the next boundary: the event is what `cancelled` consults.
            logger.warning("audit %s is no longer leased to this worker", audit_id)
            lease_lost.set()
            return
        deadline = time.monotonic() + context.lease_s


async def run_forever(
    context: WorkerContext, *, settings: Settings | None = None, stop: asyncio.Event | None = None
) -> None:
    """Recover, claim, run, sleep. The loop a deployment starts."""
    settings = settings or get_settings()
    stop = stop or asyncio.Event()
    pause = context.poll_s
    while not stop.is_set():
        try:
            requeued, abandoned = await recover(settings=settings)
            if requeued or abandoned:
                logger.info("recovered %s audit(s), abandoned %s", requeued, abandoned)
            scheduled = await run_due_schedules(settings=settings)
            if scheduled:
                logger.info("queued %s scheduled audit(s)", scheduled)
            worked = await run_once(context)
            pause = context.poll_s
        except Exception:
            # `execute` already keeps one audit's failure inside itself; this catches the parts
            # around it (recovery, schedules, the claim) so a database blip does not end the
            # process. Cancellation and shutdown are `BaseException` and still propagate.
            worked = False
            pause = error_pause(pause)
            logger.exception("worker loop failed; retrying in %.1f s", pause)
        if worked:
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=pause)
        except TimeoutError:
            continue
    logger.info("worker %s stopped", context.worker_id)


def run() -> None:
    """Console entry point: one worker process, stopped by SIGINT or SIGTERM."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    async def main() -> None:
        settings = get_settings()
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signal_name in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signal_name, stop.set)
        await run_forever(context_for(settings), settings=settings, stop=stop)

    asyncio.run(main())
