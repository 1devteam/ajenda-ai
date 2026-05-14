"""add mission planning contracts

Revision ID: 0017_add_mission_plans
Revises: 0016_retrieval_contracts
Create Date: 2026-05-13
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0017_add_mission_plans"
down_revision = "0016_retrieval_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mission_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mission_plans_tenant_id", "mission_plans", ["tenant_id"])
    op.create_index("ix_mission_plans_mission_id", "mission_plans", ["mission_id"])
    op.create_index("ix_mission_plans_mission_tenant", "mission_plans", ["mission_id", "tenant_id"])
    op.create_index(
        "uq_mission_plans_active_mission_tenant",
        "mission_plans",
        ["tenant_id", "mission_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('draft', 'ready')"),
    )

    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE mission_plans ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE mission_plans FORCE ROW LEVEL SECURITY"))
    conn.execute(
        sa.text(
            """
            CREATE POLICY tenant_mission_plan_isolation ON mission_plans
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
            CREATE POLICY admin_bypass ON mission_plans
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
    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_mission_plan_isolation ON mission_plans"))
    conn.execute(sa.text("DROP POLICY IF EXISTS admin_bypass ON mission_plans"))
    conn.execute(sa.text("ALTER TABLE mission_plans DISABLE ROW LEVEL SECURITY"))
    op.drop_index("uq_mission_plans_active_mission_tenant", table_name="mission_plans")
    op.drop_index("ix_mission_plans_mission_tenant", table_name="mission_plans")
    op.drop_index("ix_mission_plans_mission_id", table_name="mission_plans")
    op.drop_index("ix_mission_plans_tenant_id", table_name="mission_plans")
    op.drop_table("mission_plans")
