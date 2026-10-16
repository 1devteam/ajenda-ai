"""Reconcile restricted runtime roles with the observability migration branch.

The role-separation history was deployed independently at 0053 while the
observability checkpoint branch was developed from the billing head.  This
forward-only merge preserves both histories and repairs databases that reached
0053 without the checkpoint table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0054_merge_roles_evidence"
down_revision = ("0052_runtime_evidence_merge", "0053_restrict_auth_runtime")
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "runtime_evidence_consumer_checkpoints" not in inspector.get_table_names(schema="public"):
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
        op.create_index(
            "ix_runtime_evidence_consumer_checkpoint_tenant",
            "runtime_evidence_consumer_checkpoints",
            ["tenant_id", "consumer_name"],
        )
        bind.execute(sa.text("ALTER TABLE runtime_evidence_consumer_checkpoints ENABLE ROW LEVEL SECURITY"))
        bind.execute(sa.text("ALTER TABLE runtime_evidence_consumer_checkpoints FORCE ROW LEVEL SECURITY"))
        bind.execute(sa.text(
            "CREATE POLICY tenant_runtime_evidence_consumer_checkpoint_isolation "
            "ON runtime_evidence_consumer_checkpoints AS PERMISSIVE FOR ALL TO PUBLIC "
            "USING (tenant_id = current_setting('app.current_tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))"
        ))
        bind.execute(sa.text(
            "CREATE POLICY admin_bypass ON runtime_evidence_consumer_checkpoints "
            "AS PERMISSIVE FOR ALL TO ajenda_admin USING (true) WITH CHECK (true)"
        ))


def downgrade() -> None:
    # Forward recovery is required; removing evidence storage during a role
    # rollback would destroy the audit trail.
    pass
