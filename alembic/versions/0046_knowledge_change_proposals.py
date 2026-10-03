"""Add governed knowledge-change proposal lifecycle records."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0046_knowledge_change_proposals"
down_revision = "0045_stripe_revenue_payload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_change_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("proposal_id", sa.String(length=160), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("missions.id"), nullable=False),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("outcome_reviews.id"), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("target_key", sa.String(length=256), nullable=False),
        sa.Column("suggested_change", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_artifact_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("runtime_reconciliation", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="review_required"),
        sa.Column("supersedes_proposal_id", sa.String(length=160), nullable=True),
        sa.Column("superseded_by_proposal_id", sa.String(length=160), nullable=True),
        sa.Column("rollback_of_proposal_id", sa.String(length=160), nullable=True),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "proposal_id", name="uq_knowledge_change_proposals_tenant_identity"),
        sa.CheckConstraint("scope IN ('tenant_private', 'shared_candidate')", name="ck_knowledge_change_proposals_scope"),
        sa.CheckConstraint(
            "status IN ('review_required', 'accepted', 'rejected', 'superseded', 'rolled_back')",
            name="ck_knowledge_change_proposals_status",
        ),
        sa.CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_knowledge_change_proposals_confidence"),
    )
    op.create_index("ix_knowledge_change_proposals_tenant_status", "knowledge_change_proposals", ["tenant_id", "status"])
    op.create_index("ix_knowledge_change_proposals_tenant_target", "knowledge_change_proposals", ["tenant_id", "target_key"])
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE knowledge_change_proposals ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE knowledge_change_proposals FORCE ROW LEVEL SECURITY"))
    conn.execute(sa.text("""CREATE POLICY tenant_knowledge_change_proposal_isolation ON knowledge_change_proposals AS PERMISSIVE FOR ALL TO PUBLIC USING (tenant_id = current_setting('app.current_tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))"""))
    conn.execute(sa.text("""CREATE POLICY admin_bypass ON knowledge_change_proposals AS PERMISSIVE FOR ALL TO ajenda_admin USING (true) WITH CHECK (true)"""))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_knowledge_change_proposal_isolation ON knowledge_change_proposals"))
    conn.execute(sa.text("DROP POLICY IF EXISTS admin_bypass ON knowledge_change_proposals"))
    conn.execute(sa.text("ALTER TABLE knowledge_change_proposals DISABLE ROW LEVEL SECURITY"))
    op.drop_index("ix_knowledge_change_proposals_tenant_target", table_name="knowledge_change_proposals")
    op.drop_index("ix_knowledge_change_proposals_tenant_status", table_name="knowledge_change_proposals")
    op.drop_table("knowledge_change_proposals")
