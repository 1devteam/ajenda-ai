"""Persist sanitized verified Stripe payloads for revenue projections."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045_stripe_revenue_payload"
down_revision = "0044_restore_composition_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stripe_webhook_events", sa.Column("payload_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("stripe_webhook_events", "payload_json")
