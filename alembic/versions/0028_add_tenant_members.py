"""Add tenant_members table for user↔tenant membership.

Revision ID: 0028_add_tenant_members
Revises: 0027_stripe_webhook_events
Create Date: 2026-06-21

Cross-tenant membership registry (NO RLS — same rationale as tenants in 0006).
Legacy tenants without member rows continue to work via existing API keys.

No automated backfill: tenants table has no email column. Owner assignment is
manual via ops runbook (Phase 1.5).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0028_add_tenant_members"
down_revision = "0027_stripe_webhook_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("email_raw", sa.String(320), nullable=False),
        sa.Column("email_canonical", sa.String(320), nullable=False),
        sa.Column(
            "role",
            sa.String(32),
            nullable=False,
            server_default="tenant_owner",
            comment="tenant_owner | tenant_admin | operator | viewer",
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="pending_verification",
            comment="pending_verification | active | revoked",
        ),
        sa.Column("external_subject_id", sa.String(255), nullable=True),
        sa.Column("verification_token_hash", sa.String(256), nullable=True),
        sa.Column("verification_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "verification_delivery_status",
            sa.String(32),
            nullable=True,
            comment="pending | sent | failed",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_tenant_members_tenant_id", "tenant_members", ["tenant_id"])
    op.create_index("ix_tenant_members_email_canonical", "tenant_members", ["email_canonical"])
    op.create_index("ix_tenant_members_external_subject_id", "tenant_members", ["external_subject_id"])
    op.create_unique_constraint(
        "uq_tenant_members_tenant_email",
        "tenant_members",
        ["tenant_id", "email_canonical"],
    )
    op.create_index(
        "uq_tenant_members_owner_email_pending_or_active",
        "tenant_members",
        ["email_canonical"],
        unique=True,
        postgresql_where=sa.text(
            "role = 'tenant_owner' AND status IN ('active', 'pending_verification')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_tenant_members_owner_email_pending_or_active", table_name="tenant_members")
    op.drop_constraint("uq_tenant_members_tenant_email", "tenant_members", type_="unique")
    op.drop_index("ix_tenant_members_external_subject_id", table_name="tenant_members")
    op.drop_index("ix_tenant_members_email_canonical", table_name="tenant_members")
    op.drop_index("ix_tenant_members_tenant_id", table_name="tenant_members")
    op.drop_table("tenant_members")