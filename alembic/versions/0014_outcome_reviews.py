"""Add outcome review contract records.

Revision ID: 0014_outcome_reviews
Revises: 0013_evidence_contracts
Create Date: 2026-05-10 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0014_outcome_reviews"
down_revision = "0013_evidence_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outcome_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("materialization_reference", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("task_graph_reference", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reviewed_success_criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("review_decision", sa.String(length=32), nullable=False, server_default="inconclusive"),
        sa.Column("reviewer_type", sa.String(length=32), nullable=False),
        sa.Column("reviewer_source", sa.String(length=160), nullable=False),
        sa.Column("review_summary", sa.Text(), nullable=False),
        sa.Column("structured_findings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("trust_signal", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("unresolved_gaps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recommended_next_actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("human_approval_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("human_approval_status", sa.String(length=32), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "review_status IN ('draft', 'in_review', 'completed', 'superseded')",
            name="ck_outcome_reviews_review_status",
        ),
        sa.CheckConstraint(
            "review_decision IN ('accepted', 'rejected', 'partial', 'inconclusive', 'needs_human_review')",
            name="ck_outcome_reviews_review_decision",
        ),
        sa.CheckConstraint(
            "reviewer_type IN ('operator', 'system', 'policy', 'external')",
            name="ck_outcome_reviews_reviewer_type",
        ),
        sa.CheckConstraint(
            "human_approval_status IS NULL OR human_approval_status IN "
            "('not_required', 'pending', 'approved', 'rejected')",
            name="ck_outcome_reviews_human_approval_status",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_outcome_reviews_confidence",
        ),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], name="fk_outcome_reviews_mission_id"),
    )
    op.create_index("ix_outcome_reviews_tenant_id", "outcome_reviews", ["tenant_id"])
    op.create_index("ix_outcome_reviews_mission_id", "outcome_reviews", ["mission_id"])
    op.create_index("ix_outcome_reviews_mission_tenant", "outcome_reviews", ["mission_id", "tenant_id"])

    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE outcome_reviews ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE outcome_reviews FORCE ROW LEVEL SECURITY"))
    conn.execute(
        sa.text(
            """
            CREATE POLICY tenant_outcome_review_isolation ON outcome_reviews
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
            CREATE POLICY admin_bypass ON outcome_reviews
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
    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_outcome_review_isolation ON outcome_reviews"))
    conn.execute(sa.text("DROP POLICY IF EXISTS admin_bypass ON outcome_reviews"))
    conn.execute(sa.text("ALTER TABLE outcome_reviews DISABLE ROW LEVEL SECURITY"))
    op.drop_index("ix_outcome_reviews_mission_tenant", table_name="outcome_reviews")
    op.drop_index("ix_outcome_reviews_mission_id", table_name="outcome_reviews")
    op.drop_index("ix_outcome_reviews_tenant_id", table_name="outcome_reviews")
    op.drop_table("outcome_reviews")
