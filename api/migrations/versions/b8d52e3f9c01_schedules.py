"""Schedules: a page the worker audits on a rhythm.

One row per URL. `next_run_at` is the worker's permission, `enabled` is the operator's switch, and a
disabled row stays as history rather than disappearing. The foreign key to `audits` is `SET NULL`:
deleting an audit must not delete the schedule that produced it.

Revision ID: b8d52e3f9c01
Revises: a7c41d2e8b90
Create Date: 2026-11-15

Rollout: `CREATE TABLE` plus one partial index on a new table — nothing to rewrite and the new
table starts empty, but the `last_audit_id` foreign key takes `SHARE ROW EXCLUSIVE` on `audits`,
which conflicts with ordinary writes: the statement waits for the running writers and blocks new
ones until this revision commits. Bound that wait with `SET LOCAL lock_timeout = '3s'` (and a
`statement_timeout` behind it) around the revision, so a busy queue fails the deploy loudly
instead of stalling every write; a short retry, not a longer lock, is the remedy.

Rollback: `downgrade` drops the table, and with it every schedule — including disabled ones kept
as history. Nothing else can recreate the rhythm an operator chose (the audits themselves stay),
so it sits behind the same `SITEWARRANT_ALLOW_DESTRUCTIVE_DOWNGRADE=1` guard as the other
destructive revisions. Dump the rows first —

    docker exec sitewarrant-postgres-1 pg_dump -U sitewarrant --data-only \
        --table=audit_schedules sitewarrant > schedules.sql

— and restore after a re-upgrade with `psql < schedules.sql`; the rows carry their own ids, and
`last_audit_id` points at audits that still exist, so the insert needs no fix-up.
"""

from __future__ import annotations

import os

from alembic import op

revision = "b8d52e3f9c01"
down_revision = "a7c41d2e8b90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_schedules (
            id uuid PRIMARY KEY,
            site_url text NOT NULL UNIQUE,
            every_minutes integer NOT NULL,
            agents text[] NOT NULL DEFAULT '{}',
            enabled boolean NOT NULL DEFAULT true,
            next_run_at timestamptz NOT NULL,
            last_audit_id uuid REFERENCES audits(id) ON DELETE SET NULL,
            owner_id varchar(64),
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_schedules_due "
        "ON audit_schedules (next_run_at) WHERE enabled"
    )


def downgrade() -> None:
    if os.environ.get("SITEWARRANT_ALLOW_DESTRUCTIVE_DOWNGRADE") != "1":
        raise RuntimeError(
            "downgrade drops audit_schedules, and the rhythm an operator chose cannot be "
            "recomputed from the audits. Set SITEWARRANT_ALLOW_DESTRUCTIVE_DOWNGRADE=1 to proceed."
        )
    op.execute("DROP INDEX IF EXISTS ix_audit_schedules_due")
    op.execute("DROP TABLE IF EXISTS audit_schedules")
