"""Add tenant-scoped durable knowledge qualification history.

Revision ID: 0037_knowledge_ledger
Revises: 0036_composition_thread
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0037_knowledge_ledger"
down_revision = "0036_composition_thread"
branch_labels = None
depends_on = None

_TABLES = ("knowledge_qualification_records", "knowledge_artifact_records")


def upgrade() -> None:
    op.create_table(
        "knowledge_qualification_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("qualification_id", sa.String(length=128), nullable=False),
        sa.Column("proposition_key", sa.String(length=128), nullable=False),
        sa.Column("qualification_status", sa.String(length=32), nullable=False),
        sa.Column("source_candidate_id", sa.String(length=128), nullable=False),
        sa.Column("evaluation_watermark", sa.DateTime(timezone=True), nullable=True),
        sa.Column("qualification_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("algorithm", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "qualification_id", name="uq_knowledge_qualification_tenant_identity"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_knowledge_qualification_id_tenant"),
    )
    op.create_index(
        "ix_knowledge_qualification_tenant_proposition",
        "knowledge_qualification_records",
        ["tenant_id", "proposition_key"],
    )
    op.create_index(
        "ix_knowledge_qualification_tenant_status",
        "knowledge_qualification_records",
        ["tenant_id", "qualification_status"],
    )
    op.create_table(
        "knowledge_artifact_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("qualification_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_id", sa.String(length=128), nullable=False),
        sa.Column("proposition_key", sa.String(length=128), nullable=False),
        sa.Column("qualification_id", sa.String(length=128), nullable=False),
        sa.Column("source_candidate_id", sa.String(length=128), nullable=False),
        sa.Column("qualified_through_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proposition_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("artifact_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("algorithm", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["qualification_record_id", "tenant_id"],
            ["knowledge_qualification_records.id", "knowledge_qualification_records.tenant_id"],
            name="fk_knowledge_artifact_qualification_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "knowledge_id", name="uq_knowledge_artifact_tenant_identity"),
        sa.UniqueConstraint("tenant_id", "qualification_id", name="uq_knowledge_artifact_tenant_qualification"),
    )
    op.create_index(
        "ix_knowledge_artifact_tenant_proposition", "knowledge_artifact_records", ["tenant_id", "proposition_key"]
    )

    connection = op.get_bind()
    for table in _TABLES:
        connection.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO ajenda_admin"))
        connection.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        connection.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        connection.execute(
            sa.text(f"""
            CREATE POLICY tenant_isolation ON {table} AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """)
        )
        connection.execute(
            sa.text(f"""
            CREATE POLICY admin_bypass ON {table} AS PERMISSIVE FOR ALL TO ajenda_admin
            USING (true) WITH CHECK (true)
        """)
        )


def downgrade() -> None:
    connection = op.get_bind()
    for table in reversed(_TABLES):
        connection.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
        connection.execute(sa.text(f"DROP POLICY IF EXISTS admin_bypass ON {table}"))
        connection.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
        connection.execute(sa.text(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE {table} FROM ajenda_admin"))
    op.drop_index("ix_knowledge_artifact_tenant_proposition", table_name="knowledge_artifact_records")
    op.drop_table("knowledge_artifact_records")
    op.drop_index("ix_knowledge_qualification_tenant_status", table_name="knowledge_qualification_records")
    op.drop_index("ix_knowledge_qualification_tenant_proposition", table_name="knowledge_qualification_records")
    op.drop_table("knowledge_qualification_records")
