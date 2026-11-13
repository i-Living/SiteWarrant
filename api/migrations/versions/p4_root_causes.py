"""root causes

Revision ID: 9c1d7e4a55b2
Revises: 4b7c1f9d2a10

Rollout. `ADD COLUMN` on `findings` without a default is metadata-only in PostgreSQL 11+, so
`subject` and `root_cause_id` cost no table rewrite. The two operations that do take locks are the
index and the foreign key: `create_index` builds under a SHARE lock and blocks writes for the
duration, and `create_foreign_key` validates every existing row under SHARE ROW EXCLUSIVE. On this
project's data — one findings row per defect per audit, thousands of rows — both finish in well under
a second, which is why neither is built `CONCURRENTLY` (that cannot run inside the migration's
transaction anyway). Revisit if `findings` grows past a few hundred thousand rows: build the index
concurrently first, then run this revision.

Rollback. `downgrade` drops `root_causes`, `findings.root_cause_id` and `findings.subject`. The
grouping is recomputed by the next audit. `subject` is not: it comes from the agent's accepted
candidate, whose transcript is not stored, and deterministic findings derive it from the observation
(the covered selector) — so subjects of agent findings survive only if the audit is re-run with the
same agents. Accept that loss, or export `findings.subject` before a destructive downgrade
(`pg_dump --data-only -t findings`).
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
    op.add_column("findings", sa.Column("subject", sa.Text(), nullable=True))
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
    observation, agent findings do not (their transcript is not stored), so export it first if it
    has to survive.
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
