"""Give the audit a queue, a lease, an explainable confidence and a feedback record.

`audits.status` gains two values (`queued`, `cancelled`) and four columns that make the queue
recoverable: `stage`, `worker_id`, `lease_expires_at`, `attempts`, plus `cancel_requested`.
`findings.basis` stores what decided the confidence, so the float can be recomputed instead of
trusted. `finding_feedback` is a new append-only table: a reader's verdict is evidence about a
finding, and rewriting the finding would rewrite the label a benchmark derives from it.

Revision ID: a7c41d2e8b90
Revises: 5e7b2c9a41d3
Create Date: 2026-11-15

Rollout: `ADD COLUMN` with no default is metadata-only in PostgreSQL 11+, so no table rewrite —
but each statement still takes `ACCESS EXCLUSIVE` until this revision commits. `audits` and
`findings` are small (one row per page and per defect per audit; thousands here, not millions),
so the lock is seconds. On a table past a few hundred thousand rows the columns, the index and
the foreign key are three revisions, the index built `CONCURRENTLY` outside the migration
transaction and the key added `NOT VALID` then validated.

Rollback: `downgrade` drops the new columns and the feedback table. The queue's clock
(`stage`, lease, attempts) is recomputable by re-running audits, but **the feedback is not**:
it is a human verdict nothing else records. Dump it first —

    pg_dump --data-only --table=finding_feedback "$SITEWARRANT_DATABASE_URL" > feedback.sql

— and the downgrade refuses without `SITEWARRANT_ALLOW_DESTRUCTIVE_DOWNGRADE=1`, the same guard
the P0 and P3 revisions use. `findings.basis` and `confidence` are also lost; the next audit
writes them again, the old rows do not come back.
"""

from __future__ import annotations

import os

from alembic import op

revision = "a7c41d2e8b90"
down_revision = "5e7b2c9a41d3"
branch_labels = None
depends_on = None


def _refuse_blind_downgrade() -> None:
    if os.environ.get("SITEWARRANT_ALLOW_DESTRUCTIVE_DOWNGRADE") != "1":
        raise RuntimeError(
            "downgrade drops finding_feedback, which no re-run can recreate. "
            "Dump it first (pg_dump --data-only --table=finding_feedback ...) and set "
            "SITEWARRANT_ALLOW_DESTRUCTIVE_DOWNGRADE=1 to proceed."
        )


def upgrade() -> None:
    op.execute(
        "ALTER TABLE audits ADD COLUMN IF NOT EXISTS stage varchar(24), "
        "ADD COLUMN IF NOT EXISTS worker_id varchar(64), "
        "ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz, "
        "ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0, "
        "ADD COLUMN IF NOT EXISTS cancel_requested boolean NOT NULL DEFAULT false, "
        "ADD COLUMN IF NOT EXISTS owner_id varchar(64)"
    )
    op.execute("ALTER TABLE findings ADD COLUMN IF NOT EXISTS basis jsonb")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audits_status_started_at ON audits (status, started_at)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS finding_feedback (
            id uuid PRIMARY KEY,
            finding_id uuid NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
            verdict varchar(20) NOT NULL,
            source varchar(64) NOT NULL DEFAULT 'operator',
            note text,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_finding_feedback_finding_id ON finding_feedback (finding_id)"
    )


def downgrade() -> None:
    _refuse_blind_downgrade()
    op.execute("DROP INDEX IF EXISTS ix_finding_feedback_finding_id")
    op.execute("DROP TABLE IF EXISTS finding_feedback")
    op.execute("DROP INDEX IF EXISTS ix_audits_status_started_at")
    op.execute("ALTER TABLE findings DROP COLUMN IF EXISTS basis")
    op.execute(
        "ALTER TABLE audits DROP COLUMN IF EXISTS owner_id, "
        "DROP COLUMN IF EXISTS cancel_requested, "
        "DROP COLUMN IF EXISTS attempts, "
        "DROP COLUMN IF EXISTS lease_expires_at, "
        "DROP COLUMN IF EXISTS worker_id, "
        "DROP COLUMN IF EXISTS stage"
    )
