"""The heartbeat's budget: a positive backoff, and a renewal that cannot outlive the lease."""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app import worker
from app.worker import BACKOFF_MAX_S, BACKOFF_MIN_S, WorkerContext, error_pause


def test_a_zero_poll_interval_still_waits_before_the_next_attempt() -> None:
    assert error_pause(0.0) >= BACKOFF_MIN_S


def test_the_wait_doubles_and_then_holds() -> None:
    assert error_pause(1.0) == 2.0
    assert error_pause(16.0) == BACKOFF_MAX_S  # 32 is over the ceiling, so it is clamped
    assert error_pause(100.0) == BACKOFF_MAX_S


@pytest.fixture
def renewal(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A heartbeat with the database taken out: a fake session and a scripted renewal."""
    seen: dict[str, Any] = {"calls": 0}

    @contextlib.asynccontextmanager
    async def session() -> AsyncIterator[None]:
        yield None

    async def fake_renew(*_args: object, **_kwargs: object) -> bool:
        seen["calls"] += 1
        await asyncio.sleep(seen.get("delay", 0.0))
        return seen.get("answer", True)

    monkeypatch.setattr(worker, "session_scope", session)
    monkeypatch.setattr(worker.repo, "renew_lease", fake_renew)
    return seen


def context(lease_s: int) -> WorkerContext:
    return WorkerContext(worker_id="worker-a", lease_s=lease_s, poll_s=0.05, max_attempts=2)


async def test_a_success_that_lands_after_the_lease_ran_out_is_not_a_lease(renewal: dict) -> None:
    """The renewal blocks past the deadline: the heartbeat must give up, not believe the answer."""
    renewal["delay"] = 30.0
    lease_lost = asyncio.Event()
    started = time.monotonic()
    await asyncio.wait_for(
        worker._heartbeat(uuid.uuid4(), lease_lost=lease_lost, context=context(lease_s=3)),
        timeout=10,
    )
    assert lease_lost.is_set()
    # Bounded by the budget, not by the stalled call.
    assert time.monotonic() - started < 6


async def test_a_sleep_that_overruns_the_budget_does_not_renew_afterwards(renewal: dict) -> None:
    """A lease shorter than one interval is never renewed after it expired."""
    lease_lost = asyncio.Event()
    started = time.monotonic()
    await asyncio.wait_for(
        worker._heartbeat(uuid.uuid4(), lease_lost=lease_lost, context=context(lease_s=1)),
        timeout=10,
    )
    assert lease_lost.is_set()
    # At most one attempt, and it had to fit inside the second the lease had left.
    assert renewal["calls"] <= 1
    assert time.monotonic() - started < 2


async def test_a_healthy_heartbeat_renews_and_keeps_going(renewal: dict) -> None:
    lease_lost = asyncio.Event()
    heartbeat = asyncio.create_task(
        worker._heartbeat(uuid.uuid4(), lease_lost=lease_lost, context=context(lease_s=3))
    )
    for _ in range(200):
        if renewal["calls"] >= 2:
            break
        await asyncio.sleep(0.05)
    heartbeat.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await heartbeat
    assert not lease_lost.is_set()
