"""Add tenant_internal_records for Ajenda standalone brain mode.

Revision ID: 0033_tenant_internal_records
Revises: 0032_customer_auth_tables
Create Date: 2026-06-25
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0033_tenant_internal_records"
down_revision = "0032_customer_auth_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_internal_records",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("tenant_id", sa.String(length=160), nullable=False),
        sa.Column("record_type", sa.String(length=80), nullable=False),
        sa.Column("record_id", sa.String(length=160), nullable=False),
        sa.Column("data_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "record_type",
            "record_id",
            name="uq_tenant_internal_records_tenant_type_id",
        ),
    )
    op.create_index("ix_tenant_internal_records_tenant_id", "tenant_internal_records", ["tenant_id"])
    op.create_index("ix_tenant_internal_records_record_type", "tenant_internal_records", ["record_type"])
    op.create_index("ix_tenant_internal_records_record_id", "tenant_internal_records", ["record_id"])

    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE tenant_internal_records ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE tenant_internal_records FORCE ROW LEVEL SECURITY"))
    conn.execute(
        sa.text(
            """
            CREATE POLICY tenant_internal_record_isolation ON tenant_internal_records
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
            CREATE POLICY admin_bypass ON tenant_internal_records
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
    conn.execute(sa.text("DROP POLICY IF EXISTS admin_bypass ON tenant_internal_records"))
    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_internal_record_isolation ON tenant_internal_records"))
    op.drop_index("ix_tenant_internal_records_record_id", table_name="tenant_internal_records")
    op.drop_index("ix_tenant_internal_records_record_type", table_name="tenant_internal_records")
    op.drop_index("ix_tenant_internal_records_tenant_id", table_name="tenant_internal_records")
    op.drop_table("tenant_internal_records")