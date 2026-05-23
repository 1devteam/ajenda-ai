"""Add evidence contract records.

Revision ID: 0013_evidence_contracts
Revises: 0012_capability_adapters
Create Date: 2026-05-09 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0013_evidence_contracts"
down_revision = "0012_capability_adapters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_graph_node_key", sa.String(length=160), nullable=True),
        sa.Column("materialization_reference", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("execution_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("capability_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("capability_adapter_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_type", sa.String(length=64), nullable=False),
        sa.Column("evidence_source", sa.String(length=160), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("structured_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("artifact_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trust_signal", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("collection_status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "evidence_type IN "
            "('observation', 'artifact', 'decision', 'validation', 'execution_trace', "
            "'operator_note', 'external_reference')",
            name="ck_evidence_records_evidence_type",
        ),
        sa.CheckConstraint(
            "collection_status IN ('draft', 'collected', 'verified', 'rejected', 'superseded')",
            name="ck_evidence_records_collection_status",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_evidence_records_confidence"
        ),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], name="fk_evidence_records_mission_id"),
        sa.ForeignKeyConstraint(
            ["execution_task_id"], ["execution_tasks.id"], name="fk_evidence_records_execution_task_id"
        ),
        sa.ForeignKeyConstraint(["capability_id"], ["capabilities.id"], name="fk_evidence_records_capability_id"),
        sa.ForeignKeyConstraint(
            ["capability_adapter_id"], ["capability_adapters.id"], name="fk_evidence_records_capability_adapter_id"
        ),
    )
    op.create_index("ix_evidence_records_tenant_id", "evidence_records", ["tenant_id"])
    op.create_index("ix_evidence_records_mission_id", "evidence_records", ["mission_id"])
    op.create_index("ix_evidence_records_execution_task_id", "evidence_records", ["execution_task_id"])
    op.create_index("ix_evidence_records_capability_id", "evidence_records", ["capability_id"])
    op.create_index("ix_evidence_records_capability_adapter_id", "evidence_records", ["capability_adapter_id"])
    op.create_index("ix_evidence_records_mission_tenant", "evidence_records", ["mission_id", "tenant_id"])

    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE evidence_records ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE evidence_records FORCE ROW LEVEL SECURITY"))
    conn.execute(
        sa.text(
            """
            CREATE POLICY tenant_evidence_isolation ON evidence_records
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
            CREATE POLICY admin_bypass ON evidence_records
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
    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_evidence_isolation ON evidence_records"))
    conn.execute(sa.text("DROP POLICY IF EXISTS admin_bypass ON evidence_records"))
    conn.execute(sa.text("ALTER TABLE evidence_records DISABLE ROW LEVEL SECURITY"))
    op.drop_index("ix_evidence_records_mission_tenant", table_name="evidence_records")
    op.drop_index("ix_evidence_records_capability_adapter_id", table_name="evidence_records")
    op.drop_index("ix_evidence_records_capability_id", table_name="evidence_records")
    op.drop_index("ix_evidence_records_execution_task_id", table_name="evidence_records")
    op.drop_index("ix_evidence_records_mission_id", table_name="evidence_records")
    op.drop_index("ix_evidence_records_tenant_id", table_name="evidence_records")
    op.drop_table("evidence_records")
