"""Seed ability_runtime feature on pro and enterprise plans.

Revision ID: 0026_seed_ability_runtime
Revises: 0025_stripe_customer_id
Create Date: 2026-06-19

The ability-runtime launch path gates external/side-effecting actions behind the
``ability_runtime`` plan feature. Fresh installs get it from 0006; this migration
aligns upgraded databases that already ran earlier revisions.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0026_seed_ability_runtime"
down_revision = "0025_stripe_customer_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE tenant_plans
            SET
                features_enabled = CASE
                    WHEN features_enabled @> '["ability_runtime"]'::jsonb
                        THEN features_enabled
                    ELSE features_enabled || '["ability_runtime"]'::jsonb
                END,
                updated_at = now()
            WHERE slug IN ('pro', 'enterprise')
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE tenant_plans
            SET
                features_enabled = features_enabled - 'ability_runtime',
                updated_at = now()
            WHERE slug IN ('pro', 'enterprise')
            """
        )
    )