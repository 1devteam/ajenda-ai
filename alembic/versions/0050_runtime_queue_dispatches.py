"""Add durable tenant-scoped runtime queue dispatch outbox."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0050_runtime_queue_dispatches"
down_revision = "0049_continuous_assurance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_queue_dispatches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("execution_tasks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "mission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("missions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("fleet_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", name="uq_runtime_queue_dispatches_task"),
        sa.CheckConstraint(
            "status IN ('held_review', 'pending', 'published', 'cancelled')",
            name="ck_runtime_queue_dispatches_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_runtime_queue_dispatches_attempt_count"),
    )
    op.create_index("ix_runtime_queue_dispatches_tenant_id", "runtime_queue_dispatches", ["tenant_id"])
    op.create_index("ix_runtime_queue_dispatches_task_id", "runtime_queue_dispatches", ["task_id"])
    op.create_index("ix_runtime_queue_dispatches_mission_id", "runtime_queue_dispatches", ["mission_id"])
    op.create_index(
        "ix_runtime_queue_dispatches_due",
        "runtime_queue_dispatches",
        ["status", "next_attempt_at"],
    )

    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE runtime_queue_dispatches ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE runtime_queue_dispatches FORCE ROW LEVEL SECURITY"))
    conn.execute(
        sa.text(
            "CREATE POLICY tenant_runtime_queue_dispatch_isolation ON runtime_queue_dispatches "
            "AS PERMISSIVE FOR ALL TO PUBLIC "
            "USING (tenant_id = current_setting('app.current_tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))"
        )
    )
    conn.execute(
        sa.text(
            "CREATE POLICY admin_bypass ON runtime_queue_dispatches "
            "AS PERMISSIVE FOR ALL TO ajenda_admin USING (true) WITH CHECK (true)"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DROP POLICY IF EXISTS tenant_runtime_queue_dispatch_isolation ON runtime_queue_dispatches")
    )
    conn.execute(sa.text("DROP POLICY IF EXISTS admin_bypass ON runtime_queue_dispatches"))
    conn.execute(sa.text("ALTER TABLE runtime_queue_dispatches DISABLE ROW LEVEL SECURITY"))
    op.drop_index("ix_runtime_queue_dispatches_due", table_name="runtime_queue_dispatches")
    op.drop_index("ix_runtime_queue_dispatches_mission_id", table_name="runtime_queue_dispatches")
    op.drop_index("ix_runtime_queue_dispatches_task_id", table_name="runtime_queue_dispatches")
    op.drop_index("ix_runtime_queue_dispatches_tenant_id", table_name="runtime_queue_dispatches")
    op.drop_table("runtime_queue_dispatches")
