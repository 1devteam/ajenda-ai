"""Add capability registry contracts.

Revision ID: 0011_add_capability_registry
Revises: 0010_align_free_plan_contract
Create Date: 2026-05-09 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0011_add_capability_registry"
down_revision = "0010_align_free_plan_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capabilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False, server_default="1.0.0"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("supported_task_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_schema_hints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_schema_hints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("required_permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("required_tools", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False, server_default="medium"),
        sa.Column("approval_requirements", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_expectations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("execution_constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("risk_level IN ('low', 'medium', 'high', 'critical')", name="ck_capabilities_risk_level"),
    )
    op.create_index("ix_capabilities_tenant_id", "capabilities", ["tenant_id"])
    op.create_index("ix_capabilities_name", "capabilities", ["name"])
    op.create_index(
        "uq_capabilities_tenant_name_version",
        "capabilities",
        ["tenant_id", "name", "version"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )
    op.create_index(
        "uq_capabilities_global_name_version",
        "capabilities",
        ["name", "version"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
    )

    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE capabilities ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE capabilities FORCE ROW LEVEL SECURITY"))
    conn.execute(
        sa.text(
            """
            CREATE POLICY tenant_or_global_capability_visibility ON capabilities
                AS PERMISSIVE
                FOR SELECT
                TO PUBLIC
                USING (
                    tenant_id = current_setting('app.current_tenant_id', true)
                    OR tenant_id IS NULL
                )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            CREATE POLICY tenant_capability_insert ON capabilities
                AS PERMISSIVE
                FOR INSERT
                TO PUBLIC
                WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
            """
        )
    )
    conn.execute(
        sa.text(
            """
            CREATE POLICY tenant_capability_update ON capabilities
                AS PERMISSIVE
                FOR UPDATE
                TO PUBLIC
                USING (tenant_id = current_setting('app.current_tenant_id', true))
                WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
            """
        )
    )
    conn.execute(
        sa.text(
            """
            CREATE POLICY tenant_capability_delete ON capabilities
                AS PERMISSIVE
                FOR DELETE
                TO PUBLIC
                USING (tenant_id = current_setting('app.current_tenant_id', true))
            """
        )
    )
    conn.execute(
        sa.text(
            """
            CREATE POLICY admin_bypass ON capabilities
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
    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_or_global_capability_visibility ON capabilities"))
    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_capability_insert ON capabilities"))
    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_capability_update ON capabilities"))
    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_capability_delete ON capabilities"))
    conn.execute(sa.text("DROP POLICY IF EXISTS admin_bypass ON capabilities"))
    conn.execute(sa.text("ALTER TABLE capabilities DISABLE ROW LEVEL SECURITY"))
    op.drop_index("uq_capabilities_global_name_version", table_name="capabilities")
    op.drop_index("uq_capabilities_tenant_name_version", table_name="capabilities")
    op.drop_index("ix_capabilities_name", table_name="capabilities")
    op.drop_index("ix_capabilities_tenant_id", table_name="capabilities")
    op.drop_table("capabilities")
