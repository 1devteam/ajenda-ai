"""Add durable control-plane HTTP idempotency receipts.

Revision ID: 0042_http_idempotency
Revises: 0041_restore_tenant_rls
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0042_http_idempotency"
down_revision = "0041_restore_tenant_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "http_idempotency_receipts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("operation_key", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("owner_token", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_ciphertext", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_key", name="uq_http_idempotency_operation_key"),
    )
    op.create_index(
        "ix_http_idempotency_operation_key",
        "http_idempotency_receipts",
        ["operation_key"],
        unique=False,
    )
    op.create_index(
        "ix_http_idempotency_expires_at",
        "http_idempotency_receipts",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_http_idempotency_expires_at", table_name="http_idempotency_receipts")
    op.drop_index("ix_http_idempotency_operation_key", table_name="http_idempotency_receipts")
    op.drop_table("http_idempotency_receipts")
