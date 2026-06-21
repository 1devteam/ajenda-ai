"""Add signup_attempt_log for onboarding abuse observability.

Revision ID: 0030_signup_abuse_tables
Revises: 0029_api_key_bootstrap
Create Date: 2026-06-21

System-wide abuse log (NO RLS). Stores hashed client IP only — never raw IP.
Retention cleanup job deferred to Phase 1.5.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0030_signup_abuse_tables"
down_revision = "0029_api_key_bootstrap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signup_attempt_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email_canonical", sa.String(320), nullable=True),
        sa.Column(
            "client_ip_hash",
            sa.String(64),
            nullable=False,
            comment="SHA-256 hex of client IP — not raw IP",
        ),
        sa.Column("route", sa.String(64), nullable=False),
        sa.Column(
            "outcome",
            sa.String(32),
            nullable=False,
            comment="accepted | duplicate_email | rate_limited | invalid_input | error | delivery_failed",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_signup_attempt_log_email_created",
        "signup_attempt_log",
        ["email_canonical", "created_at"],
    )
    op.create_index(
        "ix_signup_attempt_log_ip_created",
        "signup_attempt_log",
        ["client_ip_hash", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_signup_attempt_log_ip_created", table_name="signup_attempt_log")
    op.drop_index("ix_signup_attempt_log_email_created", table_name="signup_attempt_log")
    op.drop_table("signup_attempt_log")