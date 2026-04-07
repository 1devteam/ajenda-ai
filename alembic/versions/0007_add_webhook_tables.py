"""Add webhook_endpoints and webhook_deliveries tables.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-07

Adds:
  - webhook_endpoints: tenant-scoped outbound webhook registrations
  - webhook_deliveries: immutable delivery attempt records

Design notes:
  - event_types uses PostgreSQL ARRAY(VARCHAR) for efficient containment
    queries using the @> operator.
  - webhook_deliveries is append-only; retries create new rows.
  - Both tables include tenant_id for RLS policy enforcement.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # webhook_endpoints
    # ------------------------------------------------------------------
    op.create_table(
        "webhook_endpoints",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Owning tenant — enforced at the application layer",
        ),
        sa.Column(
            "url",
            sa.String(2048),
            nullable=False,
            comment="HTTPS URL to deliver events to",
        ),
        sa.Column(
            "secret_hash",
            sa.String(256),
            nullable=False,
            comment="bcrypt hash of the HMAC signing secret",
        ),
        sa.Column(
            "event_types",
            postgresql.ARRAY(sa.String(64)),
            nullable=False,
            server_default="{}",
            comment="Array of event type strings this endpoint subscribes to",
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
            comment="False = endpoint disabled; deliveries are skipped",
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
    op.create_index("ix_webhook_endpoints_tenant_id", "webhook_endpoints", ["tenant_id"])
    op.create_index(
        "ix_webhook_endpoints_tenant_active",
        "webhook_endpoints",
        ["tenant_id", "is_active"],
    )

    # ------------------------------------------------------------------
    # webhook_deliveries
    # ------------------------------------------------------------------
    op.create_table(
        "webhook_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "endpoint_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="FK to webhook_endpoints.id",
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Denormalised for efficient tenant-scoped queries",
        ),
        sa.Column(
            "event_type",
            sa.String(64),
            nullable=False,
            comment="e.g. task.completed, compliance.review_required",
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Unique ID for this event — used for idempotency on retries",
        ),
        sa.Column(
            "payload",
            postgresql.JSONB,
            nullable=False,
            comment="Full JSON payload sent in the POST body",
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="pending",
            comment="pending | delivering | delivered | failed | dead_lettered",
        ),
        sa.Column(
            "attempt_number",
            sa.Integer,
            nullable=False,
            server_default="1",
            comment="1-based attempt counter for this event_id",
        ),
        sa.Column(
            "http_status_code",
            sa.Integer,
            nullable=True,
            comment="HTTP status code returned by the endpoint",
        ),
        sa.Column(
            "response_body",
            sa.Text,
            nullable=True,
            comment="First 4096 chars of the response body",
        ),
        sa.Column(
            "error_message",
            sa.String(1024),
            nullable=True,
            comment="Network or timeout error message",
        ),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="When this delivery attempt was initiated",
        ),
        sa.Column(
            "delivered_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When a 2xx response was received",
        ),
    )
    op.create_index(
        "ix_webhook_deliveries_endpoint_id", "webhook_deliveries", ["endpoint_id"]
    )
    op.create_index(
        "ix_webhook_deliveries_tenant_id", "webhook_deliveries", ["tenant_id"]
    )
    op.create_index(
        "ix_webhook_deliveries_event_id", "webhook_deliveries", ["event_id"]
    )
    op.create_index(
        "ix_webhook_deliveries_status", "webhook_deliveries", ["status"]
    )
    op.create_index(
        "ix_webhook_deliveries_tenant_status",
        "webhook_deliveries",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_endpoints")
