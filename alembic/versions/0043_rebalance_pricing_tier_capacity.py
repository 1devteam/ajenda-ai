"""Rebalance SaaS pricing-tier capacity after API metering repair.

Revision ID: 0043_pricing_tier_capacity
Revises: 0042_http_idempotency

The monthly API-call quota now measures external API-key traffic rather than
Ajenda's browser/control-plane HTTP plumbing. Rebalance the four standard plan
rows around that corrected billing unit while preserving the existing feature
entitlements and Stripe price mapping.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0043_pricing_tier_capacity"
down_revision = "0042_http_idempotency"
branch_labels = None
depends_on = None

_NEW_LIMITS: dict[str, tuple[int, int, int, int, int, int]] = {
    "free": (25, 500, 2, 1, 2, 5_000),
    "starter": (100, 5_000, 5, 3, 5, 50_000),
    "pro": (500, 50_000, 25, 10, 20, 500_000),
    "enterprise": (-1, -1, -1, -1, -1, -1),
}

_OLD_LIMITS: dict[str, tuple[int, int, int, int, int, int]] = {
    "free": (10, 100, 2, 1, 2, 1_000),
    "starter": (25, 500, 5, 3, 5, 25_000),
    "pro": (100, 5_000, 20, 10, 20, 250_000),
    "enterprise": (-1, -1, -1, -1, -1, -1),
}


def _apply_limits(limits: dict[str, tuple[int, int, int, int, int, int]]) -> None:
    connection = op.get_bind()
    statement = sa.text(
        """
        UPDATE tenant_plans
        SET
            max_missions_per_month = :missions,
            max_tasks_per_month = :tasks,
            max_agents_per_fleet = :agents,
            max_concurrent_workers = :workers,
            max_api_keys = :api_keys,
            max_monthly_api_calls = :api_calls,
            updated_at = now()
        WHERE slug = :slug
        """
    )
    for slug, values in limits.items():
        missions, tasks, agents, workers, api_keys, api_calls = values
        connection.execute(
            statement,
            {
                "slug": slug,
                "missions": missions,
                "tasks": tasks,
                "agents": agents,
                "workers": workers,
                "api_keys": api_keys,
                "api_calls": api_calls,
            },
        )


def upgrade() -> None:
    # Defaults continue to describe the entry-level contract for any future
    # plan rows that omit explicit capacity values.
    op.alter_column(
        "tenant_plans",
        "max_missions_per_month",
        existing_type=sa.Integer(),
        server_default="25",
        existing_nullable=False,
    )
    op.alter_column(
        "tenant_plans",
        "max_tasks_per_month",
        existing_type=sa.Integer(),
        server_default="500",
        existing_nullable=False,
    )
    op.alter_column(
        "tenant_plans",
        "max_monthly_api_calls",
        existing_type=sa.BigInteger(),
        server_default="5000",
        existing_nullable=False,
    )
    _apply_limits(_NEW_LIMITS)


def downgrade() -> None:
    op.alter_column(
        "tenant_plans",
        "max_missions_per_month",
        existing_type=sa.Integer(),
        server_default="10",
        existing_nullable=False,
    )
    op.alter_column(
        "tenant_plans",
        "max_tasks_per_month",
        existing_type=sa.Integer(),
        server_default="100",
        existing_nullable=False,
    )
    op.alter_column(
        "tenant_plans",
        "max_monthly_api_calls",
        existing_type=sa.BigInteger(),
        server_default="1000",
        existing_nullable=False,
    )
    _apply_limits(_OLD_LIMITS)
