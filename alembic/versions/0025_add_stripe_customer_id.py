"""Add stripe_customer_id to tenants.

Revision ID: 0025_stripe_customer_id
Revises: 0024_provider_creds
Create Date: 2026-06-15

Adds a nullable stripe_customer_id column to the tenants table.
This is required by the Stripe billing integration (Phase 1).
The column is nullable because existing tenants will not have a
Stripe customer until they initiate a checkout session.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0025_stripe_customer_id"
down_revision = "0024_provider_creds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "stripe_customer_id",
            sa.String(255),
            nullable=True,
            comment="Stripe Customer ID (cus_...). Null until first checkout.",
        ),
    )
    op.create_index(
        "ix_tenants_stripe_customer_id",
        "tenants",
        ["stripe_customer_id"],
        unique=True,
        postgresql_where=sa.text("stripe_customer_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_tenants_stripe_customer_id", table_name="tenants")
    op.drop_column("tenants", "stripe_customer_id")
