"""Add api_key_records table.

The api_key_records table was missing from the initial migration (0001).
Without it, the application crashes on first API key creation or authentication
attempt because the ORM model references a non-existent table.

This migration also adds:
- Composite operational index on (tenant_id, revoked) for fast active-key lookups
- Partial index on active (non-revoked) keys for the auth hot path
- updated_at column for auditability

Revision ID: 0002_add_api_key_records
Revises: 0001_initial_runtime_schema
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002_add_api_key_records"
down_revision = "0001_initial_runtime_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_key_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("key_id", sa.String(length=64), nullable=False, unique=True),
        # Argon2id hash — must be wide enough for the full hash string (~97 chars)
        sa.Column("hashed_secret", sa.String(length=256), nullable=False),
        sa.Column(
            "scopes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "revoked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Primary lookup index: find key by key_id (unique constraint covers this,
    # but explicit index makes the query plan visible)
    op.create_index("ix_api_key_records_key_id", "api_key_records", ["key_id"], unique=True)

    # Tenant-scoped lookup: list all keys for a tenant
    op.create_index("ix_api_key_records_tenant_id", "api_key_records", ["tenant_id"])

    # Composite index for auth hot path: tenant + active keys only
    op.create_index(
        "ix_api_key_records_tenant_active",
        "api_key_records",
        ["tenant_id", "revoked"],
    )

    # Partial index: only active (non-revoked) keys — used by auth middleware
    op.create_index(
        "ix_api_key_records_active_only",
        "api_key_records",
        ["key_id"],
        postgresql_where=sa.text("revoked = false"),
    )


def downgrade() -> None:
    op.drop_index("ix_api_key_records_active_only", table_name="api_key_records")
    op.drop_index("ix_api_key_records_tenant_active", table_name="api_key_records")
    op.drop_index("ix_api_key_records_tenant_id", table_name="api_key_records")
    op.drop_index("ix_api_key_records_key_id", table_name="api_key_records")
    op.drop_table("api_key_records")
