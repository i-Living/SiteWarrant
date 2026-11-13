"""Record what a model call was estimated to cost.

`llm_calls.cost_estimate_usd` is nullable on purpose: a model with no entry in the price file gets
NULL, and NULL reads as "not priced" instead of "free". The price version that produced the number
lives on the audit (`audits.config->>'pricing_version'`), so re-pricing an old audit with today's
rates is a deliberate migration, not a silent side effect.

Revision ID: 5e7b2c9a41d3
Revises: 9c1d7e4a55b2
Create Date: 2026-11-13

Rollout: adding a nullable column without a default is metadata-only in PostgreSQL 11+, so this
migration takes no table rewrite. Old rows keep NULL, which is exactly what they mean — the calls
were recorded before anything was priced.

Rollback: `downgrade` drops the column, and with it the estimate for every recorded call. The token
counts, latencies and trace ids survive; only the money does not. Copy it first if it matters:

    pg_dump --data-only --table=llm_calls "$SITEWARRANT_DATABASE_URL" > llm_calls.sql
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "5e7b2c9a41d3"
down_revision = "9c1d7e4a55b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("cost_estimate_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_calls", "cost_estimate_usd")
