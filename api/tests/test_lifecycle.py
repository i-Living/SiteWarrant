import pytest

from app import lifecycle


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (lifecycle.QUEUED, lifecycle.RUNNING),
        (lifecycle.QUEUED, lifecycle.CANCELLED),
        (lifecycle.RUNNING, lifecycle.COMPLETED),
        (lifecycle.RUNNING, lifecycle.PARTIAL),
        (lifecycle.RUNNING, lifecycle.FAILED),
        (lifecycle.RUNNING, lifecycle.CANCELLED),
    ],
)
def test_the_life_cycle_allows_the_moves_an_audit_makes(current: str, new: str) -> None:
    assert lifecycle.can_transition(current, new)
    lifecycle.ensure_transition(current, new)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (lifecycle.QUEUED, lifecycle.COMPLETED),
        (lifecycle.QUEUED, lifecycle.FAILED),
        (lifecycle.COMPLETED, lifecycle.RUNNING),
        (lifecycle.CANCELLED, lifecycle.COMPLETED),
        (lifecycle.FAILED, lifecycle.PARTIAL),
    ],
)
def test_an_impossible_move_is_refused(current: str, new: str) -> None:
    assert not lifecycle.can_transition(current, new)
    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.ensure_transition(current, new)


def test_repeating_a_state_is_a_no_op_not_an_error() -> None:
    """A retry that finished an already-failed row must not explode inside an error handler."""
    for status in (lifecycle.QUEUED, lifecycle.RUNNING, lifecycle.FAILED):
        assert lifecycle.can_transition(status, status)


def test_terminal_states_are_the_ones_with_no_exit() -> None:
    assert frozenset({"completed", "partial", "failed", "cancelled"}) == lifecycle.TERMINAL
    for status in lifecycle.TERMINAL:
        assert lifecycle.is_terminal(status)
    assert not lifecycle.is_terminal(lifecycle.QUEUED)
    assert not lifecycle.is_terminal(lifecycle.RUNNING)
