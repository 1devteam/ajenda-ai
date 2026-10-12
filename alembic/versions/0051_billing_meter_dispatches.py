"""Add durable tenant-scoped Stripe metering outbox."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0051_billing_meter_dispatches"
down_revision = "0050_runtime_queue_dispatches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_meter_dispatches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("stripe_subscription_item_id", sa.String(length=255), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "metric IN ('missions', 'tasks', 'agents', 'api_calls')",
            name="ck_billing_meter_dispatches_metric",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_billing_meter_dispatches_quantity"),
        sa.CheckConstraint(
            "status IN ('pending', 'delivered', 'skipped')",
            name="ck_billing_meter_dispatches_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_billing_meter_dispatches_attempt_count"),
    )
    op.create_index("ix_billing_meter_dispatches_tenant_id", "billing_meter_dispatches", ["tenant_id"])
    op.create_index(
        "ix_billing_meter_dispatches_due",
        "billing_meter_dispatches",
        ["status", "next_attempt_at"],
    )

    connection = op.get_bind()
    connection.execute(
        sa.text("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE billing_meter_dispatches TO ajenda_admin")
    )
    connection.execute(sa.text("ALTER TABLE billing_meter_dispatches ENABLE ROW LEVEL SECURITY"))
    connection.execute(sa.text("ALTER TABLE billing_meter_dispatches FORCE ROW LEVEL SECURITY"))
    connection.execute(
        sa.text(
            "CREATE POLICY tenant_isolation ON billing_meter_dispatches "
            "AS PERMISSIVE FOR ALL TO PUBLIC "
            "USING (tenant_id::text = current_setting('app.current_tenant_id', true)) "
            "WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))"
        )
    )
    connection.execute(
        sa.text(
            "CREATE POLICY admin_bypass ON billing_meter_dispatches "
            "AS PERMISSIVE FOR ALL TO ajenda_admin USING (true) WITH CHECK (true)"
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON billing_meter_dispatches"))
    connection.execute(sa.text("DROP POLICY IF EXISTS admin_bypass ON billing_meter_dispatches"))
    connection.execute(sa.text("ALTER TABLE billing_meter_dispatches DISABLE ROW LEVEL SECURITY"))
    connection.execute(
        sa.text("REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE billing_meter_dispatches FROM ajenda_admin")
    )
    op.drop_index("ix_billing_meter_dispatches_due", table_name="billing_meter_dispatches")
    op.drop_index("ix_billing_meter_dispatches_tenant_id", table_name="billing_meter_dispatches")
    op.drop_table("billing_meter_dispatches")
