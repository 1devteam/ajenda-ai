"""Add stripe_webhook_events table for webhook idempotency.

Revision ID: 0027_stripe_webhook_events
Revises: 0026_seed_ability_runtime
Create Date: 2026-06-21

Records Stripe event IDs (evt_...) to deduplicate webhook deliveries and
capture processing outcomes. System-wide table — not tenant RLS scoped.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0027_stripe_webhook_events"
down_revision = "0026_seed_ability_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stripe_webhook_events",
        sa.Column(
            "event_id",
            sa.String(255),
            primary_key=True,
            nullable=False,
            comment="Stripe event ID (evt_...)",
        ),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Resolved tenant, if any",
        ),
        sa.Column(
            "outcome",
            sa.String(32),
            nullable=False,
            comment="processing | applied | skipped | ignored",
        ),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_stripe_webhook_events_tenant_id",
        "stripe_webhook_events",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_stripe_webhook_events_tenant_id", table_name="stripe_webhook_events")
    op.drop_table("stripe_webhook_events")