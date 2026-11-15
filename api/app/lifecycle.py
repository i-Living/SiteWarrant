"""The audit's life cycle: which states exist and which moves between them are legal.

One table, one function. A status written from an arbitrary place is how a row ends up
`completed` with no report or `running` after its process died, so every write goes through
`ensure_transition`.
"""

from __future__ import annotations

QUEUED = "queued"
RUNNING = "running"
COMPLETED = "completed"
PARTIAL = "partial"
FAILED = "failed"
CANCELLED = "cancelled"

# `partial` is a report status that also lands on the row: some agents failed, the findings
# that were measured are still true. `cancelled` is the operator's decision, not a failure.
# `running -> queued` exists for one caller only: lease recovery, when the worker that held the
# row stopped renewing it. Nothing in a run may move a row back to the queue on its own.
ALLOWED: dict[str, frozenset[str]] = {
    QUEUED: frozenset({RUNNING, CANCELLED}),
    RUNNING: frozenset({QUEUED, COMPLETED, PARTIAL, FAILED, CANCELLED}),
    COMPLETED: frozenset(),
    PARTIAL: frozenset(),
    FAILED: frozenset(),
    CANCELLED: frozenset(),
}

TERMINAL = frozenset(status for status, next_states in ALLOWED.items() if not next_states)
IN_FLIGHT = frozenset({QUEUED, RUNNING})


class InvalidTransition(ValueError):
    """A write that would describe the audit as something it never was."""


def can_transition(current: str, new: str) -> bool:
    """Whether `current -> new` is a move the life cycle allows.

    The same state twice is allowed: a retry that finished a row already marked failed is a
    no-op, and refusing it would turn a harmless repeat into an exception inside an error handler.
    """
    if current == new:
        return True
    return new in ALLOWED.get(current, frozenset())


def ensure_transition(current: str, new: str) -> None:
    if not can_transition(current, new):
        raise InvalidTransition(f"an audit cannot move from {current} to {new}")


def is_terminal(status: str) -> bool:
    return status in TERMINAL
