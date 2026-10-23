"""Persist immutable, tenant-scoped business-need assessments.

Revision ID: 0056_business_need_assessments
Revises: 0055_business_understanding
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0056_business_need_assessments"
down_revision = "0055_business_understanding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_need_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("need_id", sa.String(length=128), nullable=False),
        sa.Column("need_revision", sa.Integer(), nullable=False),
        sa.Column("need_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("assessment_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("producer", sa.String(length=160), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "id", name="uq_business_need_assessments_tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "need_revision_id"],
            ["business_need_revisions.tenant_id", "business_need_revisions.id"],
            name="fk_business_need_assessments_need_revision_tenant",
        ),
    )
    op.create_index(
        "ix_business_need_assessments_tenant_need_revision",
        "business_need_assessments",
        ["tenant_id", "need_id", "need_revision"],
    )
    bind = op.get_bind()
    table = "business_need_assessments"
    bind.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    bind.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
    bind.execute(
        sa.text(
            f"CREATE POLICY tenant_business_understanding_isolation ON {table} "
            "AS PERMISSIVE FOR ALL TO PUBLIC "
            "USING (tenant_id = current_setting('app.current_tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))"
        )
    )
    bind.execute(
        sa.text(
            f"CREATE POLICY admin_bypass ON {table} AS PERMISSIVE FOR ALL TO ajenda_admin "
            "USING (true) WITH CHECK (true)"
        )
    )


def downgrade() -> None:
    table = "business_need_assessments"
    bind = op.get_bind()
    bind.execute(sa.text(f"DROP POLICY IF EXISTS tenant_business_understanding_isolation ON {table}"))
    bind.execute(sa.text(f"DROP POLICY IF EXISTS admin_bypass ON {table}"))
    bind.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
    op.drop_index("ix_business_need_assessments_tenant_need_revision", table_name=table)
    op.drop_table(table)
