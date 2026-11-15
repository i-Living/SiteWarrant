"""The queue's contract against a real database, and the label export built on feedback."""

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import lifecycle
from app.audit import LeaseLost, run_audit
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.models import Audit, Finding, Page
from app.eval.dataset import DatasetError, load_dataset
from app.eval.labels import export_labels
from app.rules.engine import FindingDraft
from app.storage import repo
from app.worker import run_due_schedules

pytestmark = pytest.mark.integration

HOST = f"labels-{uuid.uuid4().hex[:8]}.invalid"


async def wait_for_lock_waiter(session: AsyncSession, *, budget_s: float = 5.0) -> None:
    """Wait until Postgres reports a statement blocked on a lock, or fail the test.

    A fixed sleep would let the test pass whenever connection acquisition was slower than the sleep:
    recovery would commit first and the heartbeat would never contend. `pg_stat_activity` says when
    the contention actually exists.
    """
    # Give the other task a clean slot before the first poll: polling straight after the lock is
    # taken can run the whole budget without the renewal ever opening its connection.
    await asyncio.sleep(0.05)
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        waiting = await session.scalar(
            text(
                "select count(*) from pg_stat_activity "
                "where wait_event_type = 'Lock' and query ilike '%UPDATE audits%'"
            )
        )
        if waiting:
            return
        await asyncio.sleep(0.02)
    rows = (
        await session.execute(
            text("select pid, state, wait_event_type, left(query, 60) from pg_stat_activity")
        )
    ).all()
    pytest.fail(f"the renewal never reached the database: {rows}")


async def drain() -> None:
    """Take leftover queued rows out of the way: no worker is coming for them in a test run."""
    async with session_scope() as session:
        rows = (
            await session.execute(select(Audit).where(Audit.status == lifecycle.QUEUED))
        ).scalars()
        for row in rows:
            row.status = lifecycle.CANCELLED
            row.error = "left over from another test"
            row.finished_at = datetime.now(UTC)
        await session.commit()


async def enqueue(url: str = HOST, *, status: str = lifecycle.QUEUED) -> uuid.UUID:
    site_url = url if url.startswith("http") else f"http://{url}/"
    async with session_scope() as session:
        return await repo.create_audit(
            session,
            site_url=site_url,
            agent_version="sha256:test",
            config={"agents": [], "viewports": ["390x844"]},
            status=status,
        )


async def test_the_oldest_queued_audit_is_claimed_once() -> None:
    await drain()
    first = await enqueue("queue-one.invalid")
    second = await enqueue("queue-two.invalid")
    async with session_scope() as session:
        claimed_a = await repo.claim_audit(session, worker_id="worker-a", lease_s=60)
    async with session_scope() as session:
        claimed_b = await repo.claim_audit(session, worker_id="worker-b", lease_s=60)
    async with session_scope() as session:
        claimed_c = await repo.claim_audit(session, worker_id="worker-b", lease_s=60)
    # The queue is oldest-first, and `first` was written before `second`.
    assert claimed_a is not None and claimed_a[0] == first
    assert claimed_b is not None and claimed_b[0] == second
    assert claimed_c is None, "a claimed audit is not handed to a second worker"
    async with session_scope() as session:
        row = await repo.get_audit(session, first)
    assert row is not None
    assert row.status == lifecycle.RUNNING
    assert row.worker_id == "worker-a"
    assert row.attempts == 1


async def test_a_lease_that_expired_returns_the_audit_to_the_queue() -> None:
    await drain()
    audit_id = await enqueue("queue-lease.invalid")
    async with session_scope() as session:
        claimed = await repo.claim_audit(session, worker_id="worker-a", lease_s=60)
    assert claimed is not None and claimed[0] == audit_id
    async with session_scope() as session:
        row = await repo.get_audit(session, audit_id)
        assert row is not None
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    async with session_scope() as session:
        requeued, _abandoned = await repo.requeue_expired(session, max_attempts=2)
    # Other rows in a shared database may also have expired; the one under test must be back.
    assert requeued >= 1
    async with session_scope() as session:
        row = await repo.get_audit(session, audit_id)
    assert row is not None
    assert row.status == lifecycle.QUEUED
    assert row.worker_id is None


async def test_an_audit_out_of_attempts_is_failed_not_looped_forever() -> None:
    await drain()
    audit_id = await enqueue("queue-abandon.invalid")
    async with session_scope() as session:
        await repo.claim_audit(session, worker_id="worker-a", lease_s=60)
    async with session_scope() as session:
        row = await repo.get_audit(session, audit_id)
        assert row is not None
        row.attempts = 2
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    async with session_scope() as session:
        _requeued, abandoned = await repo.requeue_expired(session, max_attempts=2)
    assert abandoned >= 1
    async with session_scope() as session:
        row = await repo.get_audit(session, audit_id)
    assert row is not None
    assert row.status == lifecycle.FAILED
    assert row.error is not None and "lease" in row.error


async def test_a_queued_audit_is_cancelled_at_once_and_a_running_one_is_asked() -> None:
    await drain()
    queued_id = await enqueue("queue-cancel.invalid")
    async with session_scope() as session:
        cancelled = await repo.request_cancel(session, queued_id)
    assert cancelled is not None and cancelled.status == lifecycle.CANCELLED
    assert cancelled.finished_at is not None

    running_id = await enqueue("queue-cancel-running.invalid")
    async with session_scope() as session:
        await repo.claim_audit(session, worker_id="worker-a", lease_s=60)
    async with session_scope() as session:
        asked = await repo.request_cancel(session, running_id)
    assert asked is not None and asked.status == lifecycle.RUNNING
    assert asked.cancel_requested is True
    async with session_scope() as session:
        assert await repo.cancel_requested(session, running_id) is True


async def test_recovery_skips_an_audit_whose_facts_transaction_is_open() -> None:
    """A page insert locks the audit row for key share, so recovery skips it instead of racing."""
    await drain()
    audit_id = await enqueue("facts-lock.invalid")
    async with session_scope() as session:
        await repo.claim_audit(session, worker_id="worker-a", lease_s=0)  # expired on arrival
    async with session_scope() as facts:
        await repo.save_page(
            facts,
            audit_id=audit_id,
            url="http://facts-lock.invalid/",
            key="facts-lock.invalid",
            status_code=200,
            render_mode="browser",
        )
        async with session_scope() as recovery:
            await repo.requeue_expired(recovery, max_attempts=2)
        async with session_scope() as check:
            held = await repo.get_audit(check, audit_id)
        # Recovery's `FOR UPDATE ... SKIP LOCKED` skipped the row the facts transaction holds.
        assert held is not None and held.status == lifecycle.RUNNING
        await facts.rollback()
    async with session_scope() as recovery:
        await repo.requeue_expired(recovery, max_attempts=2)
    async with session_scope() as check:
        after = await repo.get_audit(check, audit_id)
    assert after is not None and after.status == lifecycle.QUEUED


async def test_a_rejected_final_write_rolls_the_last_commit_back() -> None:
    """A row reclaimed at the last stage: the report is fenced, and the findings go with it."""
    await drain()
    url = "http://localhost:8081/"
    audit_id = await enqueue(url)
    async with session_scope() as session:
        await repo.claim_audit(session, worker_id="worker-a", lease_s=60)

    async def reclaim(stage: str) -> None:
        if stage != "report":
            return
        async with session_scope() as session:
            row = await repo.get_audit(session, audit_id)
            assert row is not None
            row.worker_id = "worker-b"
            await session.commit()

    with pytest.raises(LeaseLost):
        await run_audit(
            url,
            allow_private=True,
            audit_id=audit_id,
            worker_id="worker-a",
            attempt=1,
            progress=reclaim,
        )
    async with session_scope() as session:
        row = await repo.get_audit(session, audit_id)
        findings = await repo.findings_for_audit(session, audit_id)
    assert row is not None
    assert row.worker_id == "worker-b"
    assert row.report_key is None
    assert findings == []


async def test_usage_from_two_attempts_of_one_audit_is_added_not_overwritten() -> None:
    """Totals are a SQL increment: two attempts recording at once must both count."""
    await drain()
    audit_id = await enqueue("usage.invalid")

    async def record(tokens: int) -> None:
        async with session_scope() as session:
            await repo.add_audit_usage(
                session,
                audit_id=audit_id,
                tokens_in=tokens,
                tokens_out=tokens,
                llm_calls=1,
                cost_estimate_usd=0.5,
            )
            await session.commit()

    async with session_scope() as stale:
        # The attempt that will lose the row records first, and its transaction stays open while
        # the row is reclaimed: the next attempt's increment is already waiting on this row lock.
        await repo.add_audit_usage(
            stale,
            audit_id=audit_id,
            tokens_in=10,
            tokens_out=10,
            llm_calls=1,
            cost_estimate_usd=0.5,
        )
        next_attempt = asyncio.create_task(record(5))
        await asyncio.sleep(0.2)
        row = await stale.get(Audit, audit_id)
        assert row is not None
        row.worker_id = "worker-b"
        await stale.commit()
    await asyncio.wait_for(next_attempt, timeout=10)
    async with session_scope() as session:
        row = await session.get(Audit, audit_id)
    assert row is not None
    assert (row.tokens_in, row.tokens_out, row.llm_calls) == (15, 15, 2)
    assert row.cost_estimate_usd == pytest.approx(1.0)


async def test_a_heartbeat_cannot_renew_a_lease_recovery_is_holding() -> None:
    """The renewal is one conditional UPDATE: a row recovery took cannot be stamped back."""
    await drain()
    audit_id = await enqueue("heartbeat.invalid")
    async with session_scope() as session:
        claimed = await repo.claim_audit(session, worker_id="worker-a", lease_s=60)
    assert claimed is not None and claimed[0] == audit_id, "the queue handed over a different row"

    async def beat() -> bool:
        async with session_scope() as session:
            return await repo.renew_lease(
                session, audit_id=audit_id, worker_id="worker-a", lease_s=60
            )

    async with session_scope() as recovery:
        await recovery.execute(select(Audit).where(Audit.id == audit_id).with_for_update())
        # The row is locked first, so the heartbeat's UPDATE has to wait for this transaction;
        # wait for the database to say it is waiting instead of guessing with a sleep.
        heartbeat = asyncio.create_task(beat())
        await wait_for_lock_waiter(recovery)
        row = await recovery.get(Audit, audit_id)
        assert row is not None
        row.status = lifecycle.QUEUED
        row.worker_id = None
        await recovery.commit()
    assert await asyncio.wait_for(heartbeat, timeout=10) is False


async def test_a_reclaim_before_the_facts_commit_stops_the_run() -> None:
    """The commit that agents need is a commit a reclaimed run must not make."""
    await drain()
    url = "http://localhost:8081/"
    audit_id = await enqueue(url)
    async with session_scope() as session:
        await repo.claim_audit(session, worker_id="worker-a", lease_s=60)

    async def reclaim(stage: str) -> None:
        if stage != "facts":
            return
        # Another worker takes the row while this run is still between stages.
        async with session_scope() as session:
            row = await repo.get_audit(session, audit_id)
            assert row is not None
            row.worker_id = "worker-b"
            await session.commit()

    with pytest.raises(LeaseLost):
        await run_audit(
            url,
            allow_private=True,
            agents=("a11y",),
            audit_id=audit_id,
            worker_id="worker-a",
            attempt=1,
            progress=reclaim,
        )
    async with session_scope() as session:
        row = await repo.get_audit(session, audit_id)
        findings = await repo.findings_for_audit(session, audit_id)
        pages = (
            (await session.execute(select(Page).where(Page.audit_id == audit_id))).scalars().all()
        )
    assert row is not None
    assert row.worker_id == "worker-b"
    assert row.status == lifecycle.RUNNING
    assert row.report_key is None
    # The facts of the losing run were rolled back with its transaction.
    assert findings == [] and pages == []


async def test_recovery_discards_the_dead_attempts_facts() -> None:
    """The next attempt must not see the previous one's pages: its agents would cite them."""
    await drain()
    audit_id = await enqueue("queue-clean.invalid")
    async with session_scope() as session:
        claimed = await repo.claim_audit(session, worker_id="worker-a", lease_s=0)
    assert claimed is not None and claimed[0] == audit_id
    async with session_scope() as session:
        page_id = await repo.save_page(
            session,
            audit_id=audit_id,
            url="http://queue-clean.invalid/",
            key="queue-clean.invalid",
            status_code=200,
            render_mode="browser",
        )
        await repo.save_findings(
            session, audit_id=audit_id, page_id=page_id, drafts=[draft("SEO-TITLE", "seo")]
        )
        await session.commit()
    async with session_scope() as session:
        requeued, _abandoned = await repo.requeue_expired(session, max_attempts=2)
        assert requeued >= 1
    async with session_scope() as session:
        row = await repo.get_audit(session, audit_id)
        findings = await repo.findings_for_audit(session, audit_id)
    assert row is not None and row.status == lifecycle.QUEUED
    assert findings == []


async def test_a_reclaimed_audit_fences_the_stale_worker() -> None:
    """The fence is in storage: a worker that lost the row writes nothing, not even a stage."""
    await drain()
    audit_id = await enqueue("queue-fence.invalid")
    async with session_scope() as session:
        claimed = await repo.claim_audit(session, worker_id="worker-a", lease_s=60)
    assert claimed is not None and claimed[0] == audit_id
    async with session_scope() as session:
        # The row is still worker-a's: the fence is on identity, not on a timer.
        assert await repo.set_stage(session, audit_id=audit_id, stage="facts", worker_id="worker-a")
        assert not await repo.set_stage(
            session, audit_id=audit_id, stage="chief", worker_id="worker-b"
        )
        assert not await repo.finish_audit(
            session,
            audit_id=audit_id,
            status=lifecycle.COMPLETED,
            pages_count=1,
            report_key="audits/x/report.json",
            worker_id="worker-b",
        )
        await session.commit()
    async with session_scope() as session:
        row = await repo.get_audit(session, audit_id)
    assert row is not None
    assert row.status == lifecycle.RUNNING
    assert row.worker_id == "worker-a"
    assert row.stage == "facts"
    assert row.report_key is None


async def test_a_finished_audit_refuses_a_second_terminal_state() -> None:
    await drain()
    audit_id = await enqueue("queue-finish.invalid")
    async with session_scope() as session:
        await repo.claim_audit(session, worker_id="worker-a", lease_s=60)
    async with session_scope() as session:
        assert await repo.finish_audit(
            session,
            audit_id=audit_id,
            status=lifecycle.COMPLETED,
            pages_count=1,
            report_key=None,
        )
        await session.commit()
    async with session_scope() as session:
        assert not await repo.finish_audit(
            session,
            audit_id=audit_id,
            status=lifecycle.CANCELLED,
            pages_count=1,
            report_key=None,
        )
        await session.commit()
    async with session_scope() as session:
        row = await repo.get_audit(session, audit_id)
    assert row is not None and row.status == lifecycle.COMPLETED


def draft(rule_id: str, category: str) -> FindingDraft:
    return FindingDraft(
        rule_id=rule_id,
        category=category,
        severity="major",
        title="t",
        summary="s",
        suggested_fix="f",
        impact_conversion=0,
        impact_seo=2 if category == "seo" else 0,
        impact_ux=2 if category == "a11y" else 0,
        confidence=1.0,
        agent="rules",
        evidence=[],
    )


async def test_a_page_is_labelled_only_when_every_finding_was_reviewed(tmp_path: Path) -> None:
    audit_id = await enqueue(f"http://{HOST}/pricing", status=lifecycle.COMPLETED)
    async with session_scope() as session:
        page_id = await repo.save_page(
            session,
            audit_id=audit_id,
            url=f"http://{HOST}/pricing",
            key=HOST,
            status_code=200,
            render_mode="browser",
        )
        stored = await repo.save_findings(
            session,
            audit_id=audit_id,
            page_id=page_id,
            drafts=[
                draft("SEO-TITLE", "seo"),
                draft("A11Y-LANG", "a11y"),
                # One rule can fire twice on a page (two covered links); a label is stated at
                # (rule, page), so these two findings are one labelled defect.
                draft("SEO-TITLE", "seo"),
            ],
        )
        await session.commit()
    confirmed, false_positive, second_confirmed = stored[0][0], stored[1][0], stored[2][0]

    out = tmp_path / "labels.json"
    # One finding still unreviewed: the page is not fully labelled, so it is absent.
    async with session_scope() as session:
        await repo.add_feedback(
            session, finding_id=confirmed, verdict="confirmed", source="operator", note=None
        )
    with pytest.raises(DatasetError, match="no page"):
        await export_labels(HOST, out=out)

    async with session_scope() as session:
        await repo.add_feedback(
            session,
            finding_id=false_positive,
            verdict="false_positive",
            source="operator",
            note=None,
        )
        await repo.add_feedback(
            session,
            finding_id=second_confirmed,
            verdict="confirmed",
            source="operator",
            note=None,
        )
    manifest = await export_labels(HOST, out=out)
    assert manifest["totals"] == {"sites": 1, "pages": 1, "labels": 1}
    dataset = load_dataset(out)
    assert dataset.source == "live"
    site = dataset.sites[0]
    # The audited URL, not a path: a live corpus is fetched from the internet, and the query
    # string is part of which page it is.
    assert site.pages == (f"http://{HOST}/pricing",)
    assert [(label.page, label.rule_id) for label in site.labels] == [
        (f"http://{HOST}/pricing", "SEO-TITLE")
    ]
    # The false positive is a page with no label, which is the control for precision.
    assert "A11Y-LANG" not in {label.rule_id for label in site.labels}


async def test_a_withdrawn_verdict_leaves_no_label(tmp_path: Path) -> None:
    """Feedback is append-only: the export must read the last verdict, not any verdict."""
    await drain()
    host = f"withdrawn-{uuid.uuid4().hex[:8]}.invalid"
    audit_id = await enqueue(f"http://{host}/p", status=lifecycle.COMPLETED)
    async with session_scope() as session:
        page_id = await repo.save_page(
            session,
            audit_id=audit_id,
            url=f"http://{host}/p",
            key=host,
            status_code=200,
            render_mode="browser",
        )
        stored = await repo.save_findings(
            session, audit_id=audit_id, page_id=page_id, drafts=[draft("SEO-TITLE", "seo")]
        )
        await session.commit()
    finding_id = stored[0][0]
    async with session_scope() as session:
        await repo.add_feedback(
            session, finding_id=finding_id, verdict="confirmed", source="operator", note=None
        )
        await repo.add_feedback(
            session, finding_id=finding_id, verdict="false_positive", source="operator", note=None
        )
    manifest = await export_labels(host, out=tmp_path / "withdrawn.json")
    # The page is reviewed, so it is a clean control: its defect was withdrawn.
    assert manifest["totals"] == {"sites": 1, "pages": 1, "labels": 0}


async def test_feedback_never_rewrites_the_finding() -> None:
    await drain()
    host = f"immutable-{uuid.uuid4().hex[:8]}.invalid"
    audit_id = await enqueue(f"http://{host}/p", status=lifecycle.COMPLETED)
    async with session_scope() as session:
        page_id = await repo.save_page(
            session,
            audit_id=audit_id,
            url=f"http://{host}/p",
            key=host,
            status_code=200,
            render_mode="browser",
        )
        stored = await repo.save_findings(
            session, audit_id=audit_id, page_id=page_id, drafts=[draft("SEO-TITLE", "seo")]
        )
        await session.commit()
    finding_id = stored[0][0]
    async with session_scope() as session:
        await repo.add_feedback(
            session, finding_id=finding_id, verdict="false_positive", source="operator", note="ok"
        )
    async with session_scope() as session:
        finding = await session.get(Finding, finding_id)
        assert finding is not None
        assert finding.title == "t"
        assert finding.confidence == 1.0


async def make_due_schedule(url: str, *, every_minutes: int = 60) -> uuid.UUID:
    async with session_scope() as session:
        schedule, _created = await repo.upsert_schedule(
            session,
            site_url=url,
            every_minutes=every_minutes,
            agents=[],
            owner_id="test",
        )
        schedule.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()
        return schedule.id


async def test_a_due_schedule_queues_one_audit_and_moves_forward() -> None:
    url = f"http://schedule-{uuid.uuid4().hex[:8]}.invalid/"
    schedule_id = await make_due_schedule(url)
    settings = get_settings()
    # Other schedules in a shared database may also be due; only this one is under the assertion.
    await run_due_schedules(settings=settings)
    async with session_scope() as session:
        schedule = await repo.get_schedule(session, schedule_id)
        assert schedule is not None
        assert schedule.next_run_at > datetime.now(UTC)
        assert schedule.last_audit_id is not None
        audit = await repo.get_audit(session, schedule.last_audit_id)
        audits = (await session.execute(select(Audit).where(Audit.site_url == url))).scalars().all()
    assert audit is not None
    assert audit.site_url == url
    assert audit.status == lifecycle.QUEUED
    assert len(audits) == 1
    # Not due again: the second loop must not queue a second audit.
    await run_due_schedules(settings=settings)
    async with session_scope() as session:
        audits = (await session.execute(select(Audit).where(Audit.site_url == url))).scalars().all()
    assert len(audits) == 1


async def test_a_schedule_waits_while_the_page_is_already_in_flight() -> None:
    url = f"http://schedule-busy-{uuid.uuid4().hex[:8]}.invalid/"
    schedule_id = await make_due_schedule(url)
    await enqueue(url)
    settings = get_settings()
    await run_due_schedules(settings=settings)
    async with session_scope() as session:
        schedule = await repo.get_schedule(session, schedule_id)
        assert schedule is not None
        assert schedule.last_audit_id is None, "the in-flight run is not this schedule's"
        # Pushed by the retry delay, not by a whole interval: the in-flight run is the answer.
        delay = schedule.next_run_at - datetime.now(UTC)
        assert timedelta(seconds=30) < delay < timedelta(minutes=2)


async def test_a_disabled_schedule_does_not_run() -> None:
    url = f"http://schedule-off-{uuid.uuid4().hex[:8]}.invalid/"
    schedule_id = await make_due_schedule(url)
    async with session_scope() as session:
        await repo.set_schedule_enabled(session, schedule_id, False)
        schedule = await repo.get_schedule(session, schedule_id)
        assert schedule is not None
        schedule.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()
    settings = get_settings()
    await run_due_schedules(settings=settings)
    async with session_scope() as session:
        schedule = await repo.get_schedule(session, schedule_id)
        assert schedule is not None
        assert schedule.last_audit_id is None
