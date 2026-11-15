"""The loop's error backoff: positive, bounded, and independent of a zero poll interval."""

from __future__ import annotations

from app.worker import BACKOFF_MAX_S, BACKOFF_MIN_S, error_pause


def test_a_zero_poll_interval_still_waits_before_the_next_attempt() -> None:
    assert error_pause(0.0) >= BACKOFF_MIN_S


def test_the_wait_doubles_and_then_holds() -> None:
    assert error_pause(1.0) == 2.0
    assert error_pause(16.0) == BACKOFF_MAX_S  # 32 is over the ceiling, so it is clamped
    assert error_pause(100.0) == BACKOFF_MAX_S
