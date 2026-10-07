"""Add tenant-scoped continuous assurance history."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0049_continuous_assurance"
down_revision = "0048_profile_reversion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assurance_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("missions.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("observation_fingerprint", sa.String(length=80), nullable=False),
        sa.Column("first_divergence", sa.String(length=500), nullable=True),
        sa.Column("finding_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("findings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("runtime_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reconciliation_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("epistemic_confidence", sa.Float(), nullable=True),
        sa.Column("calibration_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("calibration_outcome_aligned", sa.Boolean(), nullable=True),
        sa.Column("authority_class", sa.String(length=32), nullable=False, server_default="read_model"),
        sa.Column("grants_execution_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('aligned', 'incomplete', 'drifted', 'contradictory')",
            name="ck_assurance_snapshots_status",
        ),
        sa.CheckConstraint(
            "authority_class = 'read_model' AND grants_execution_authority = false",
            name="ck_assurance_snapshots_authority",
        ),
        sa.CheckConstraint(
            "epistemic_confidence IS NULL OR (epistemic_confidence >= 0 AND epistemic_confidence <= 1)",
            name="ck_assurance_snapshots_confidence",
        ),
    )
    op.create_index(
        "ix_assurance_snapshots_tenant_observed",
        "assurance_snapshots",
        ["tenant_id", "observed_at"],
    )
    op.create_index(
        "ix_assurance_snapshots_tenant_status",
        "assurance_snapshots",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_assurance_snapshots_mission_observed",
        "assurance_snapshots",
        ["mission_id", "observed_at"],
    )
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE assurance_snapshots ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE assurance_snapshots FORCE ROW LEVEL SECURITY"))
    conn.execute(
        sa.text(
            "CREATE POLICY tenant_assurance_snapshot_isolation ON assurance_snapshots "
            "AS PERMISSIVE FOR ALL TO PUBLIC "
            "USING (tenant_id = current_setting('app.current_tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))"
        )
    )
    conn.execute(
        sa.text(
            "CREATE POLICY admin_bypass ON assurance_snapshots "
            "AS PERMISSIVE FOR ALL TO ajenda_admin USING (true) WITH CHECK (true)"
        )
    )

    op.create_table(
        "assurance_metric_state",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("snapshot_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("aligned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("incomplete_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("drifted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contradictory_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_divergence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("calibration_sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("calibration_aligned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tenant_failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_assurance_metric_state_singleton"),
    )
    op.execute(
        sa.text(
            "INSERT INTO assurance_metric_state "
            "(id, snapshot_count, aligned_count, incomplete_count, drifted_count, contradictory_count, "
            "first_divergence_count, calibration_sample_count, calibration_aligned_count, tenant_failure_count) "
            "VALUES (1, 0, 0, 0, 0, 0, 0, 0, 0, 0)"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_assurance_snapshot_isolation ON assurance_snapshots"))
    conn.execute(sa.text("DROP POLICY IF EXISTS admin_bypass ON assurance_snapshots"))
    conn.execute(sa.text("ALTER TABLE assurance_snapshots DISABLE ROW LEVEL SECURITY"))
    op.drop_index("ix_assurance_snapshots_mission_observed", table_name="assurance_snapshots")
    op.drop_index("ix_assurance_snapshots_tenant_status", table_name="assurance_snapshots")
    op.drop_index("ix_assurance_snapshots_tenant_observed", table_name="assurance_snapshots")
    op.drop_table("assurance_metric_state")
    op.drop_table("assurance_snapshots")
