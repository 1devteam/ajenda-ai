"""Add independent consumer checkpoints for runtime evidence replay."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0050_runtime_evidence_ckpts"
down_revision = "0049_continuous_assurance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_evidence_consumer_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("missions.id"), nullable=False),
        sa.Column("consumer_name", sa.String(length=128), nullable=False),
        sa.Column("last_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'processed', 'failed')", name="ck_runtime_evidence_consumer_checkpoint_status"),
        sa.UniqueConstraint("tenant_id", "mission_id", "consumer_name", name="uq_runtime_evidence_consumer_checkpoint"),
    )
    op.create_index("ix_runtime_evidence_consumer_checkpoint_tenant", "runtime_evidence_consumer_checkpoints", ["tenant_id", "consumer_name"])
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE runtime_evidence_consumer_checkpoints ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE runtime_evidence_consumer_checkpoints FORCE ROW LEVEL SECURITY"))
    conn.execute(sa.text("CREATE POLICY tenant_runtime_evidence_consumer_checkpoint_isolation ON runtime_evidence_consumer_checkpoints AS PERMISSIVE FOR ALL TO PUBLIC USING (tenant_id = current_setting('app.current_tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))"))
    conn.execute(sa.text("CREATE POLICY admin_bypass ON runtime_evidence_consumer_checkpoints AS PERMISSIVE FOR ALL TO ajenda_admin USING (true) WITH CHECK (true)"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_runtime_evidence_consumer_checkpoint_isolation ON runtime_evidence_consumer_checkpoints"))
    conn.execute(sa.text("DROP POLICY IF EXISTS admin_bypass ON runtime_evidence_consumer_checkpoints"))
    conn.execute(sa.text("ALTER TABLE runtime_evidence_consumer_checkpoints DISABLE ROW LEVEL SECURITY"))
    op.drop_index("ix_runtime_evidence_consumer_checkpoint_tenant", table_name="runtime_evidence_consumer_checkpoints")
    op.drop_table("runtime_evidence_consumer_checkpoints")
