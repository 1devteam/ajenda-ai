"""add retrieval and recall contracts

Revision ID: 0016_retrieval_contracts
Revises: 0015_memory_promotions
Create Date: 2026-05-10
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0016_retrieval_contracts"
down_revision = "0015_memory_promotions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retrieval_contracts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retrieval_request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("retrieval_reason", sa.Text(), nullable=False),
        sa.Column("retrieval_strategy", sa.String(length=64), nullable=False),
        sa.Column("strategy_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("retrieval_filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("governance_constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("memory_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("returned_memory_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("trust_signal", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("retrieval_status", sa.String(length=32), nullable=False),
        sa.Column("superseded_by_retrieval_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revocation_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_retrieval_contracts_tenant_id", "retrieval_contracts", ["tenant_id"])
    op.create_index("ix_retrieval_contracts_mission_id", "retrieval_contracts", ["mission_id"])
    op.create_index(
        "ix_retrieval_contracts_mission_tenant", "retrieval_contracts", ["mission_id", "tenant_id"]
    )
    op.create_index(
        "ix_retrieval_contracts_superseded_by_retrieval_id",
        "retrieval_contracts",
        ["superseded_by_retrieval_id"],
    )

    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE retrieval_contracts ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE retrieval_contracts FORCE ROW LEVEL SECURITY"))
    conn.execute(
        sa.text(
            """
            CREATE POLICY tenant_retrieval_contract_isolation ON retrieval_contracts
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
            CREATE POLICY admin_bypass ON retrieval_contracts
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
    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_retrieval_contract_isolation ON retrieval_contracts"))
    conn.execute(sa.text("DROP POLICY IF EXISTS admin_bypass ON retrieval_contracts"))
    conn.execute(sa.text("ALTER TABLE retrieval_contracts DISABLE ROW LEVEL SECURITY"))
    op.drop_index("ix_retrieval_contracts_superseded_by_retrieval_id", table_name="retrieval_contracts")
    op.drop_index("ix_retrieval_contracts_mission_tenant", table_name="retrieval_contracts")
    op.drop_index("ix_retrieval_contracts_mission_id", table_name="retrieval_contracts")
    op.drop_index("ix_retrieval_contracts_tenant_id", table_name="retrieval_contracts")
    op.drop_table("retrieval_contracts")
