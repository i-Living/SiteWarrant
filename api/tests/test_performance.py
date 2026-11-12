import pytest

from app.tools.performance import (
    CLS_WINDOW_GAP_MS,
    CLS_WINDOW_MAX_MS,
    cls_session_window,
    total_blocking_time,
)


def test_two_shifts_far_apart_are_two_windows_and_the_worst_one_counts() -> None:
    """0.1 + 0.1 a minute apart is CLS 0.1, not 0.2."""
    assert cls_session_window([(0.0, 0.1), (60_000.0, 0.1)]) == pytest.approx(0.1)


def test_shifts_inside_the_gap_share_a_window() -> None:
    assert cls_session_window([(0.0, 0.1), (500.0, 0.1)]) == pytest.approx(0.2)


def test_a_shift_exactly_at_the_gap_boundary_starts_a_new_window() -> None:
    assert cls_session_window([(0.0, 0.1), (CLS_WINDOW_GAP_MS, 0.1)]) == pytest.approx(0.1)


def test_a_window_closes_when_it_reaches_five_seconds() -> None:
    """Shifts 900 ms apart stay in one window until it spans five seconds."""
    shifts = [(index * 900.0, 0.1) for index in range(7)]
    # 0 … 4500 ms fit in one window (0.6); the shift at 5400 starts a new one.
    assert CLS_WINDOW_MAX_MS <= 5_400.0 - 0.0
    assert cls_session_window(shifts) == pytest.approx(0.6)


def test_no_shifts_is_zero() -> None:
    assert cls_session_window([]) == 0.0


def test_a_task_before_the_first_paint_does_not_block() -> None:
    """A 200 ms task that finished before FCP delayed nothing visible."""
    assert total_blocking_time([(10.0, 200.0)], first_paint_ms=100.0, end_ms=5_000.0) == 0.0


def test_a_task_after_the_first_paint_contributes_its_overhead() -> None:
    assert total_blocking_time([(150.0, 200.0)], first_paint_ms=100.0, end_ms=5_000.0) == 150.0


def test_a_task_after_the_measurement_window_is_excluded() -> None:
    """The probes run script; their long tasks are the auditor's, not the page's."""
    assert total_blocking_time([(6_000.0, 200.0)], first_paint_ms=100.0, end_ms=5_000.0) == 0.0


def test_short_tasks_add_nothing() -> None:
    assert total_blocking_time([(150.0, 40.0)], first_paint_ms=100.0, end_ms=5_000.0) == 0.0


def test_without_a_first_paint_there_is_no_interval() -> None:
    assert total_blocking_time([(150.0, 200.0)], first_paint_ms=None, end_ms=5_000.0) == 0.0
