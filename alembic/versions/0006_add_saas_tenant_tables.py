"""Add SaaS tenant tables: tenants, tenant_plans, tenant_usage.

Revision ID: 0006
Revises: 0005
Create Date: 2025-01-01 00:00:00.000000

This migration creates the three tables that form the SaaS structural
enforcement layer:

  tenants        — Root tenant record with lifecycle state and plan slug.
  tenant_plans   — Subscription plan definitions with per-tier limits.
  tenant_usage   — Monthly usage metering counters per tenant.

It also seeds the four standard plan tiers (free, starter, pro, enterprise)
so that the application can enforce quotas immediately after migration.

Indexes:
  - tenants.slug (unique) — plan lookup join key
  - tenants.status        — lifecycle queries
  - tenant_usage (tenant_id, billing_period_start) (unique) — metering queries

RLS: The tenants table is NOT covered by the tenant RLS policy (migration 0003)
because it is a cross-tenant admin table. It is accessible only to the
ajenda_admin role in production.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # tenants table
    # ------------------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="active",
            comment="active | suspended | deleted",
        ),
        sa.Column(
            "plan",
            sa.String(32),
            nullable=False,
            server_default="free",
            comment="free | starter | pro | enterprise",
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_unique_constraint("uq_tenants_slug", "tenants", ["slug"])
    op.create_index("ix_tenants_slug", "tenants", ["slug"])
    op.create_index("ix_tenants_status", "tenants", ["status"])

    # ------------------------------------------------------------------
    # tenant_plans table
    # ------------------------------------------------------------------
    op.create_table(
        "tenant_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        # Limits (-1 = unlimited)
        sa.Column("max_missions_per_month", sa.Integer, nullable=False, server_default="10"),
        sa.Column("max_tasks_per_month", sa.Integer, nullable=False, server_default="100"),
        sa.Column("max_agents_per_fleet", sa.Integer, nullable=False, server_default="5"),
        sa.Column("max_concurrent_workers", sa.Integer, nullable=False, server_default="2"),
        sa.Column("max_api_keys", sa.Integer, nullable=False, server_default="3"),
        sa.Column(
            "max_monthly_api_calls", sa.BigInteger, nullable=False, server_default="10000"
        ),
        # Feature flags
        sa.Column(
            "features_enabled",
            postgresql.JSONB,
            nullable=False,
            server_default="'[]'::jsonb",
            comment="Array of feature flag strings enabled for this plan",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_unique_constraint("uq_tenant_plans_slug", "tenant_plans", ["slug"])
    op.create_index("ix_tenant_plans_slug", "tenant_plans", ["slug"])

    # ------------------------------------------------------------------
    # tenant_usage table
    # ------------------------------------------------------------------
    op.create_table(
        "tenant_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "billing_period_start",
            sa.Date,
            nullable=False,
            comment="First day of the billing month (UTC)",
        ),
        # Cumulative counters
        sa.Column("missions_created", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("tasks_created", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("api_calls_count", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("agents_provisioned", sa.BigInteger, nullable=False, server_default="0"),
        # Gauge
        sa.Column("active_workers", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_tenant_usage_period",
        "tenant_usage",
        ["tenant_id", "billing_period_start"],
    )
    op.create_index("ix_tenant_usage_tenant_id", "tenant_usage", ["tenant_id"])
    op.create_index(
        "ix_tenant_usage_tenant_period",
        "tenant_usage",
        ["tenant_id", "billing_period_start"],
    )

    # ------------------------------------------------------------------
    # Seed standard plan tiers
    # ------------------------------------------------------------------
    now = datetime.now(tz=UTC)
    plans_table = sa.table(
        "tenant_plans",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("slug", sa.String),
        sa.column("display_name", sa.String),
        sa.column("max_missions_per_month", sa.Integer),
        sa.column("max_tasks_per_month", sa.Integer),
        sa.column("max_agents_per_fleet", sa.Integer),
        sa.column("max_concurrent_workers", sa.Integer),
        sa.column("max_api_keys", sa.Integer),
        sa.column("max_monthly_api_calls", sa.BigInteger),
        sa.column("features_enabled", postgresql.JSONB),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        plans_table,
        [
            {
                "id": uuid.uuid4(),
                "slug": "free",
                "display_name": "Free",
                "max_missions_per_month": 5,
                "max_tasks_per_month": 50,
                "max_agents_per_fleet": 2,
                "max_concurrent_workers": 1,
                "max_api_keys": 2,
                "max_monthly_api_calls": 1_000,
                "features_enabled": [],
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": uuid.uuid4(),
                "slug": "starter",
                "display_name": "Starter",
                "max_missions_per_month": 25,
                "max_tasks_per_month": 500,
                "max_agents_per_fleet": 5,
                "max_concurrent_workers": 3,
                "max_api_keys": 5,
                "max_monthly_api_calls": 25_000,
                "features_enabled": ["webhooks"],
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": uuid.uuid4(),
                "slug": "pro",
                "display_name": "Pro",
                "max_missions_per_month": 100,
                "max_tasks_per_month": 5_000,
                "max_agents_per_fleet": 20,
                "max_concurrent_workers": 10,
                "max_api_keys": 20,
                "max_monthly_api_calls": 250_000,
                "features_enabled": [
                    "webhooks",
                    "compliance_layer",
                    "custom_oidc",
                    "audit_export",
                ],
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": uuid.uuid4(),
                "slug": "enterprise",
                "display_name": "Enterprise",
                "max_missions_per_month": -1,
                "max_tasks_per_month": -1,
                "max_agents_per_fleet": -1,
                "max_concurrent_workers": -1,
                "max_api_keys": -1,
                "max_monthly_api_calls": -1,
                "features_enabled": [
                    "webhooks",
                    "compliance_layer",
                    "custom_oidc",
                    "audit_export",
                    "sso",
                    "custom_retention",
                    "dedicated_workers",
                    "sla_support",
                ],
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("tenant_usage")
    op.drop_table("tenant_plans")
    op.drop_table("tenants")
