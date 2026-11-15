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
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app import lifecycle
from app.audit import AuditCancelled, audit_config, current_agent_version, run_audit
from app.core.config import Settings, get_settings
from app.core.db import session_scope
from app.storage import repo

logger = logging.getLogger(__name__)

# A due schedule whose page is already being audited waits this long before it looks again: the
# in-flight run is the answer to the schedule's own question, and a second browser would only
# duplicate the bill.
SCHEDULE_RETRY_S = 60


@dataclass(frozen=True)
class WorkerContext:
    """Who is working, for how long the lease lasts, and how often to look for work."""

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
    await execute(audit_id, url, context=context)
    return True


async def execute(audit_id: uuid.UUID, url: str, *, context: WorkerContext) -> None:
    """Run one claimed audit, renewing the lease while it works.

    A failure is the audit's, never the worker's: `audit_page` has already written the reason on
    the row, and the loop has to keep going or one broken URL would stop the queue.
    """

    async def progress(stage: str) -> None:
        async with session_scope() as session:
            await repo.set_stage(session, audit_id=audit_id, stage=stage)

    async def cancelled() -> bool:
        async with session_scope() as session:
            return await repo.cancel_requested(session, audit_id)

    heartbeat = asyncio.create_task(_heartbeat(audit_id, context=context), name=f"lease-{audit_id}")
    try:
        await run_audit(url, audit_id=audit_id, progress=progress, cancelled=cancelled)
    except AuditCancelled:
        logger.info("audit %s was cancelled", audit_id)
    except Exception:
        logger.exception("audit %s failed", audit_id)
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)


async def _heartbeat(audit_id: uuid.UUID, *, context: WorkerContext) -> None:
    """Keep the lease alive while the audit runs; stop when another worker owns the row."""
    interval = max(1.0, context.lease_s / 3)
    while True:
        await asyncio.sleep(interval)
        async with session_scope() as session:
            renewed = await repo.renew_lease(
                session,
                audit_id=audit_id,
                worker_id=context.worker_id,
                lease_s=context.lease_s,
            )
        if not renewed:
            logger.warning("audit %s is no longer leased to this worker", audit_id)
            return


async def run_forever(
    context: WorkerContext, *, settings: Settings | None = None, stop: asyncio.Event | None = None
) -> None:
    """Recover, claim, run, sleep. The loop a deployment starts."""
    settings = settings or get_settings()
    stop = stop or asyncio.Event()
    while not stop.is_set():
        requeued, abandoned = await recover(settings=settings)
        if requeued or abandoned:
            logger.info("recovered %s audit(s), abandoned %s", requeued, abandoned)
        scheduled = await run_due_schedules(settings=settings)
        if scheduled:
            logger.info("queued %s scheduled audit(s)", scheduled)
        if await run_once(context):
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=context.poll_s)
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
