"""Add provider runtime credentials table.

Revision ID: 0024_provider_creds
Revises: 0023_adapter_side_effects
Create Date: 2026-06-13
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0024_provider_creds"
down_revision = "0023_adapter_side_effects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_runtime_credentials",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("tenant_id", sa.String(length=160), nullable=False),
        sa.Column("credential_id", sa.String(length=160), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("credential_type", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("allowed_actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("allowed_side_effect_classes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trusted_destination_hosts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "credential_id",
            name="uq_provider_runtime_credentials_tenant_credential",
        ),
    )
    op.create_index(
        "ix_provider_runtime_credentials_tenant_id",
        "provider_runtime_credentials",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_provider_runtime_credentials_credential_id",
        "provider_runtime_credentials",
        ["credential_id"],
        unique=False,
    )

    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE provider_runtime_credentials ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE provider_runtime_credentials FORCE ROW LEVEL SECURITY"))
    conn.execute(
        sa.text(
            """
            CREATE POLICY tenant_provider_runtime_credential_isolation ON provider_runtime_credentials
                AS PERMISSIVE
                FOR ALL
                TO PUBLIC
                USING (tenant_id = current_setting('app.current_tenant_id', true))
                WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
            """
        )
    )
    conn.execute(
        sa.text(
            """
            CREATE POLICY admin_bypass ON provider_runtime_credentials
                AS PERMISSIVE
                FOR ALL
                TO ajenda_admin
                USING (true)
                WITH CHECK (true)
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DROP POLICY IF EXISTS tenant_provider_runtime_credential_isolation ON provider_runtime_credentials")
    )
    conn.execute(sa.text("DROP POLICY IF EXISTS admin_bypass ON provider_runtime_credentials"))
    conn.execute(sa.text("ALTER TABLE provider_runtime_credentials DISABLE ROW LEVEL SECURITY"))
    op.drop_index("ix_provider_runtime_credentials_credential_id", table_name="provider_runtime_credentials")
    op.drop_index("ix_provider_runtime_credentials_tenant_id", table_name="provider_runtime_credentials")
    op.drop_table("provider_runtime_credentials")
