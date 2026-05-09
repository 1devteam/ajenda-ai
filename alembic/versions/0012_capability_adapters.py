"""Add capability execution adapter contracts.

Revision ID: 0012_capability_adapters
Revises: 0011_add_capability_registry
Create Date: 2026-05-09 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0012_capability_adapters"
down_revision = "0011_add_capability_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capability_adapters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False, server_default="1.0.0"),
        sa.Column("capability_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("capability_name", sa.String(length=160), nullable=True),
        sa.Column("capability_version", sa.String(length=64), nullable=True),
        sa.Column("supported_task_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_contract", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_contract", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("required_permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("required_tools", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("execution_mode", sa.String(length=32), nullable=False, server_default="declarative"),
        sa.Column("risk_level", sa.String(length=32), nullable=False, server_default="medium"),
        sa.Column("approval_requirements", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_expectations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("timeout_retry_hints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_expectations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("side_effect_classification", sa.String(length=64), nullable=False, server_default="none"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "execution_mode IN ('declarative', 'manual', 'synchronous', 'asynchronous', 'queued')",
            name="ck_capability_adapters_execution_mode",
        ),
        sa.CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical')",
            name="ck_capability_adapters_risk_level",
        ),
        sa.CheckConstraint(
            "side_effect_classification IN "
            "('none', 'read_only', 'idempotent_write', 'non_idempotent_write', 'external_side_effect')",
            name="ck_capability_adapters_side_effect_classification",
        ),
        sa.CheckConstraint(
            "(capability_name IS NULL AND capability_version IS NULL) OR "
            "(capability_name IS NOT NULL AND capability_version IS NOT NULL)",
            name="ck_capability_adapters_capability_name_version_pair",
        ),
        sa.CheckConstraint(
            "capability_id IS NOT NULL OR "
            "(capability_name IS NOT NULL AND capability_version IS NOT NULL)",
            name="ck_capability_adapters_requires_capability_binding",
        ),
        sa.ForeignKeyConstraint(["capability_id"], ["capabilities.id"], name="fk_capability_adapters_capability_id"),
    )
    op.create_index("ix_capability_adapters_tenant_id", "capability_adapters", ["tenant_id"])
    op.create_index("ix_capability_adapters_capability_id", "capability_adapters", ["capability_id"])
    op.create_index("ix_capability_adapters_name", "capability_adapters", ["name"])
    op.create_index(
        "uq_capability_adapters_tenant_name_version",
        "capability_adapters",
        ["tenant_id", "name", "version"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )
    op.create_index(
        "uq_capability_adapters_global_name_version",
        "capability_adapters",
        ["name", "version"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
    )

    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE capability_adapters ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE capability_adapters FORCE ROW LEVEL SECURITY"))
    conn.execute(
        sa.text(
            """
            CREATE POLICY tenant_or_global_capability_adapter_visibility ON capability_adapters
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
            CREATE POLICY tenant_capability_adapter_insert ON capability_adapters
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
            CREATE POLICY tenant_capability_adapter_update ON capability_adapters
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
            CREATE POLICY tenant_capability_adapter_delete ON capability_adapters
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
            CREATE POLICY admin_bypass ON capability_adapters
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
    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_or_global_capability_adapter_visibility ON capability_adapters"))
    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_capability_adapter_insert ON capability_adapters"))
    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_capability_adapter_update ON capability_adapters"))
    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_capability_adapter_delete ON capability_adapters"))
    conn.execute(sa.text("DROP POLICY IF EXISTS admin_bypass ON capability_adapters"))
    conn.execute(sa.text("ALTER TABLE capability_adapters DISABLE ROW LEVEL SECURITY"))
    op.drop_index("uq_capability_adapters_global_name_version", table_name="capability_adapters")
    op.drop_index("uq_capability_adapters_tenant_name_version", table_name="capability_adapters")
    op.drop_index("ix_capability_adapters_name", table_name="capability_adapters")
    op.drop_index("ix_capability_adapters_capability_id", table_name="capability_adapters")
    op.drop_index("ix_capability_adapters_tenant_id", table_name="capability_adapters")
    op.drop_table("capability_adapters")
