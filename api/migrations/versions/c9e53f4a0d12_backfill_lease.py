"""Give audits interrupted before the queue a lease, so recovery can see them.

`requeue_expired` recovers `running` rows whose lease expired. A row written by a process that died
before the queue existed has NULL in `lease_expires_at`, which is not "expired" and matches nothing:
without this pass such a row stays `running` forever and no worker will ever pick it up.

Revision ID: c9e53f4a0d12
Revises: b8d52e3f9c01
Create Date: 2026-11-15

Rollout: one `UPDATE` over `running` rows with a NULL lease; `audits` holds one row per audit
(thousands here), so the lock is seconds. Run it **after the old API process has stopped** — a
process still running an audit would keep working on a row the worker then requeues, and the two
would write the same files. Bound the wait with `SET LOCAL lock_timeout = '3s'` like the schedule
revision if the queue is busy.

Rollback: deliberately a no-op. Clearing the lease again would only make recovery blind to a row
that is still `running`; an expired lease and a NULL one describe the same abandoned audit, and
`downgrade` of `a7c41d2e8b90` drops the column anyway.
"""

from __future__ import annotations

from alembic import op

revision = "c9e53f4a0d12"
down_revision = "b8d52e3f9c01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE audits SET lease_expires_at = now() "
        "WHERE status = 'running' AND lease_expires_at IS NULL"
    )


def downgrade() -> None:
    """Nothing to undo: the value only makes an abandoned row recoverable."""
