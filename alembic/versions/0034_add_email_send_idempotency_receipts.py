"""Add email_send_idempotency_receipts for SMTP send replay protection.

Revision ID: 0034_email_send_idempotency
Revises: 0033_tenant_internal_records
Create Date: 2026-07-19

SMTP and platform_master email credentials have no provider-side Idempotency-Key
semantics. This table records a durable claim *before* sendmail so worker
retries under the same key cannot deliver a second message.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0034_email_send_idempotency"
down_revision = "0033_tenant_internal_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_send_idempotency_receipts",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("tenant_id", sa.String(length=160), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            comment="claiming | completed",
        ),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "action",
            "idempotency_key",
            name="uq_email_send_idempotency_tenant_action_key",
        ),
    )
    op.create_index(
        "ix_email_send_idempotency_receipts_tenant_id",
        "email_send_idempotency_receipts",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_send_idempotency_receipts_tenant_id",
        table_name="email_send_idempotency_receipts",
    )
    op.drop_table("email_send_idempotency_receipts")
