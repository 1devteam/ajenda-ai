"""Align free-plan quotas for upgraded environments.

Revision ID: 0010_align_free_plan_contract
Revises: 0009
Create Date: 2026-04-14 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0010_align_free_plan_contract"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Align defaults for future inserts.
    op.alter_column(
        "tenant_plans",
        "max_agents_per_fleet",
        existing_type=sa.Integer(),
        server_default="2",
        existing_nullable=False,
    )
    op.alter_column(
        "tenant_plans",
        "max_concurrent_workers",
        existing_type=sa.Integer(),
        server_default="1",
        existing_nullable=False,
    )
    op.alter_column(
        "tenant_plans",
        "max_api_keys",
        existing_type=sa.Integer(),
        server_default="2",
        existing_nullable=False,
    )
    op.alter_column(
        "tenant_plans",
        "max_monthly_api_calls",
        existing_type=sa.BigInteger(),
        server_default="1000",
        existing_nullable=False,
    )

    # Align existing upgraded databases.
    op.execute(
        sa.text(
            """
            UPDATE tenant_plans
            SET
                max_missions_per_month = 10,
                max_tasks_per_month = 100,
                max_agents_per_fleet = 2,
                max_concurrent_workers = 1,
                max_api_keys = 2,
                max_monthly_api_calls = 1000,
                updated_at = now()
            WHERE slug = 'free'
            """
        )
    )


def downgrade() -> None:
    op.alter_column(
        "tenant_plans",
        "max_agents_per_fleet",
        existing_type=sa.Integer(),
        server_default="5",
        existing_nullable=False,
    )
    op.alter_column(
        "tenant_plans",
        "max_concurrent_workers",
        existing_type=sa.Integer(),
        server_default="2",
        existing_nullable=False,
    )
    op.alter_column(
        "tenant_plans",
        "max_api_keys",
        existing_type=sa.Integer(),
        server_default="3",
        existing_nullable=False,
    )
    op.alter_column(
        "tenant_plans",
        "max_monthly_api_calls",
        existing_type=sa.BigInteger(),
        server_default="10000",
        existing_nullable=False,
    )

    op.execute(
        sa.text(
            """
            UPDATE tenant_plans
            SET
                max_missions_per_month = 10,
                max_tasks_per_month = 100,
                max_agents_per_fleet = 2,
                max_concurrent_workers = 1,
                max_api_keys = 2,
                max_monthly_api_calls = 1000,
                updated_at = now()
            WHERE slug = 'free'
            """
        )
    )
