"""root causes

Revision ID: 9c1d7e4a55b2
Revises: 4b7c1f9d2a10

Rollout. `ADD COLUMN` without a default is metadata-only in PostgreSQL 11+, so `subject` and
`root_cause_id` do not rewrite the table — but the ALTERs still take `ACCESS EXCLUSIVE` on `findings`,
and Alembic runs this revision in one transaction, so that lock is held until commit, through the
index build and the foreign-key validation. On this table — one findings row per defect per audit,
thousands of rows — the whole revision takes seconds and blocks reads and writes for that long. If
`findings` ever grows past a few hundred thousand rows, split it: a revision for the columns, one
that builds `ix_findings_root_cause_id` with `CREATE INDEX CONCURRENTLY` (autocommit, outside the
migration transaction), and one that adds the foreign key with `NOT VALID` followed by
`VALIDATE CONSTRAINT`. The index cannot be built before the column exists, and this revision creates
it, which is why the fallback has to be a split rather than a concurrent build here.

Rollback. `downgrade` drops `root_causes`, `findings.root_cause_id` and `findings.subject`. The
grouping is recomputed by the next audit. A `subject` is not: deterministic findings rebuild it from
the observation, agent findings cannot — the transcript is not stored — and re-running the audit
creates new findings, it does not restore subjects on the rows that already exist. Either accept the
loss or export before the downgrade (`pg_dump --data-only -t findings`) and restore afterwards by
finding id: load the dump into a staging table and
`UPDATE findings SET subject = staging.subject FROM staging WHERE findings.id = staging.id`.
"""

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "9c1d7e4a55b2"
down_revision = "4b7c1f9d2a10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "root_causes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "audit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("audits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "page_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cause_kind", sa.String(length=32), nullable=False),
        sa.Column("anchor", sa.String(length=512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "categories",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_root_causes_audit_id", "root_causes", ["audit_id"])
    # Idempotent on purpose: an unmerged branch database may already hold this column from an
    # earlier form of this revision, where it was String(256). No released environment can,
    # because the revision ships with this PR.
    op.execute("ALTER TABLE findings ADD COLUMN IF NOT EXISTS subject text")
    op.execute("ALTER TABLE findings ALTER COLUMN subject TYPE text")
    op.add_column(
        "findings",
        sa.Column("root_cause_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_findings_root_cause_id", "findings", ["root_cause_id"])
    op.create_foreign_key(
        "fk_findings_root_cause_id",
        "findings",
        "root_causes",
        ["root_cause_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Clusters are derived from findings; subjects are not.

    The findings themselves stay. The grouping goes and the next audit recomputes it. The
    per-finding `subject` goes with the column: deterministic findings rebuild it from the
    observation, agent findings do not (their transcript is not stored), and re-running the audit
    writes new rows instead of restoring old ones. Export it first if it has to survive, and restore
    it by finding id after re-upgrading.
    """
    if os.environ.get("SITEWARRANT_ALLOW_DESTRUCTIVE_DOWNGRADE") != "1":
        raise RuntimeError(
            "downgrade drops the root_cause grouping and every findings.subject of existing "
            "audits; agent subjects cannot be recomputed without re-running the audit. "
            "Export them first (pg_dump --data-only -t findings) or set "
            "SITEWARRANT_ALLOW_DESTRUCTIVE_DOWNGRADE=1 to proceed"
        )
    op.execute("ALTER TABLE findings DROP CONSTRAINT IF EXISTS fk_findings_root_cause_id")
    op.execute("DROP INDEX IF EXISTS ix_findings_root_cause_id")
    op.execute("ALTER TABLE findings DROP COLUMN IF EXISTS root_cause_id")
    op.execute("ALTER TABLE findings DROP COLUMN IF EXISTS subject")
    op.execute("DROP INDEX IF EXISTS ix_root_causes_audit_id")
    op.execute("DROP TABLE IF EXISTS root_causes")
