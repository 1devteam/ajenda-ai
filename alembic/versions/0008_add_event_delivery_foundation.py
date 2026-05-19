"""Add event delivery foundation.

Revision ID: 0008_add_event_delivery_foundation
Revises: 0007_add_saas_tenant_tables
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008_add_event_delivery_foundation"
down_revision = "0007_add_saas_tenant_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("destination_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column(
            "payload_json",
            postgresql.JSONB(),
            nullable=False,
            server_default="'{}'::jsonb",
        ),
        sa.Column(
            "headers_json",
            postgresql.JSONB(),
            nullable=False,
            server_default="'{}'::jsonb",
        ),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_event_deliveries_tenant_id", "event_deliveries", ["tenant_id"])
    op.create_index("ix_event_deliveries_event_type", "event_deliveries", ["event_type"])
    op.create_index("ix_event_deliveries_status", "event_deliveries", ["status"])
    op.create_index("ix_event_deliveries_mission_id", "event_deliveries", ["mission_id"])
    op.create_unique_constraint(
        "uq_event_deliveries_tenant_id_idempotency_key",
        "event_deliveries",
        ["tenant_id", "idempotency_key"],
    )
    op.create_index(
        "ix_event_deliveries_idempotency_key",
        "event_deliveries",
        ["idempotency_key"],
    )


def downgrade() -> None:
    op.drop_table("event_deliveries")
