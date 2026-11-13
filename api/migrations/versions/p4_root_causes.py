"""root causes

Revision ID: 9c1d7e4a55b2
Revises: 4b7c1f9d2a10
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
    op.add_column("findings", sa.Column("subject", sa.String(length=256), nullable=True))
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
    """Clusters are derived from findings, so dropping them loses no measurement.

    The findings themselves stay; only the grouping goes, which the next audit recomputes.
    """
    if os.environ.get("SITEWARRANT_ALLOW_DESTRUCTIVE_DOWNGRADE") != "1":
        raise RuntimeError(
            "downgrade drops the root_cause grouping of existing audits; "
            "set SITEWARRANT_ALLOW_DESTRUCTIVE_DOWNGRADE=1 to proceed"
        )
    op.execute("ALTER TABLE findings DROP CONSTRAINT IF EXISTS fk_findings_root_cause_id")
    op.execute("DROP INDEX IF EXISTS ix_findings_root_cause_id")
    op.execute("ALTER TABLE findings DROP COLUMN IF EXISTS root_cause_id")
    op.execute("ALTER TABLE findings DROP COLUMN IF EXISTS subject")
    op.execute("DROP INDEX IF EXISTS ix_root_causes_audit_id")
    op.execute("DROP TABLE IF EXISTS root_causes")
