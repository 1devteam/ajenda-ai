"""Add OIDC login intents and customer auth sessions.

Revision ID: 0032_customer_auth_tables
Revises: 0031_backfill_mission_plans
Create Date: 2026-06-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_customer_auth_tables"
down_revision = "0031_backfill_mission_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oidc_login_intents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("redirect_uri", sa.String(length=2048), nullable=False),
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("client_ip_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_oidc_login_intents_expires_at", "oidc_login_intents", ["expires_at"])

    op.create_table(
        "customer_auth_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("member_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("access_jti", sa.String(length=64), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_ip_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["member_id"], ["tenant_members.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("access_jti"),
        sa.UniqueConstraint("refresh_token_hash"),
    )
    op.create_index("ix_customer_auth_sessions_member_id", "customer_auth_sessions", ["member_id"])
    op.create_index("ix_customer_auth_sessions_tenant_id", "customer_auth_sessions", ["tenant_id"])
    op.create_index("ix_customer_auth_sessions_expires_at", "customer_auth_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_customer_auth_sessions_expires_at", table_name="customer_auth_sessions")
    op.drop_index("ix_customer_auth_sessions_tenant_id", table_name="customer_auth_sessions")
    op.drop_index("ix_customer_auth_sessions_member_id", table_name="customer_auth_sessions")
    op.drop_table("customer_auth_sessions")
    op.drop_index("ix_oidc_login_intents_expires_at", table_name="oidc_login_intents")
    op.drop_table("oidc_login_intents")