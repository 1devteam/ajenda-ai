"""add business profile storage contracts

Revision ID: 0022_add_business_profiles
Revises: 0021_seed_gtm_capability_catalog
Create Date: 2026-06-03
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0022_add_business_profiles"
down_revision = "0021_seed_gtm_capability_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("approved_facts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'archived', 'superseded')", name="ck_business_profiles_status"),
    )
    op.create_index("ix_business_profiles_tenant_id", "business_profiles", ["tenant_id"])
    op.create_index(
        "uq_business_profiles_active_tenant",
        "business_profiles",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "business_profile_suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("suggested_category", sa.String(length=96), nullable=False),
        sa.Column("suggested_fact", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rationale", sa.String(length=500), nullable=False),
        sa.Column("source_context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("resolution", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'edited', 'declined', 'dismissed', 'superseded')",
            name="ck_business_profile_suggestions_status",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["business_profiles.id"], name="fk_business_profile_suggestions_profile_id"
        ),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], name="fk_business_profile_suggestions_mission_id"),
    )
    op.create_index("ix_business_profile_suggestions_tenant_id", "business_profile_suggestions", ["tenant_id"])
    op.create_index("ix_business_profile_suggestions_profile_id", "business_profile_suggestions", ["profile_id"])
    op.create_index("ix_business_profile_suggestions_mission_id", "business_profile_suggestions", ["mission_id"])
    op.create_index(
        "ix_business_profile_suggestions_tenant_status",
        "business_profile_suggestions",
        ["tenant_id", "status"],
    )

    conn = op.get_bind()
    for table_name in ("business_profiles", "business_profile_suggestions"):
        conn.execute(sa.text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))
        conn.execute(sa.text(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY"))

    conn.execute(
        sa.text(
            """
            CREATE POLICY tenant_business_profile_isolation ON business_profiles
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
            CREATE POLICY admin_bypass ON business_profiles
                AS PERMISSIVE
                FOR ALL
                TO ajenda_admin
                USING (true)
                WITH CHECK (true)
            """
        )
    )
    conn.execute(
        sa.text(
            """
            CREATE POLICY tenant_business_profile_suggestion_isolation ON business_profile_suggestions
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
            CREATE POLICY admin_bypass ON business_profile_suggestions
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
        sa.text("DROP POLICY IF EXISTS tenant_business_profile_suggestion_isolation ON business_profile_suggestions")
    )
    conn.execute(sa.text("DROP POLICY IF EXISTS admin_bypass ON business_profile_suggestions"))
    conn.execute(sa.text("ALTER TABLE business_profile_suggestions DISABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_business_profile_isolation ON business_profiles"))
    conn.execute(sa.text("DROP POLICY IF EXISTS admin_bypass ON business_profiles"))
    conn.execute(sa.text("ALTER TABLE business_profiles DISABLE ROW LEVEL SECURITY"))
    op.drop_index("ix_business_profile_suggestions_tenant_status", table_name="business_profile_suggestions")
    op.drop_index("ix_business_profile_suggestions_mission_id", table_name="business_profile_suggestions")
    op.drop_index("ix_business_profile_suggestions_profile_id", table_name="business_profile_suggestions")
    op.drop_index("ix_business_profile_suggestions_tenant_id", table_name="business_profile_suggestions")
    op.drop_table("business_profile_suggestions")
    op.drop_index("uq_business_profiles_active_tenant", table_name="business_profiles")
    op.drop_index("ix_business_profiles_tenant_id", table_name="business_profiles")
    op.drop_table("business_profiles")
