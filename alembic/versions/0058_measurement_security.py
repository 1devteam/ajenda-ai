"""Secure and deduplicate authoritative business measurements.

Revision ID: 0058_measurement_security
Revises: 0057_assessment_retry_dedup
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0058_measurement_security"
down_revision = "0057_assessment_retry_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Some databases applied the originally published 0057, which only added
    # assessment retry deduplication. Repair that forward-compatible state
    # here rather than assuming Alembic will rerun an already-recorded 0057.
    if not inspector.has_table("business_measurements"):
        op.create_table(
            "business_measurements",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", sa.String(length=128), nullable=False),
            sa.Column("subject_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("objective_key", sa.String(length=160), nullable=False),
            sa.Column("metric", sa.String(length=160), nullable=False),
            sa.Column("values", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("value", sa.Float(), nullable=True),
            sa.Column("unit", sa.String(length=40), nullable=False),
            sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source_kind", sa.String(length=32), nullable=False),
            sa.Column("source_reference", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("source_version", sa.String(length=160), nullable=False),
            sa.Column("source_content_fingerprint", sa.String(length=128), nullable=False),
            sa.Column("limitations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_business_measurements_tenant_id", "business_measurements", ["tenant_id"])
    observation_columns = {column["name"] for column in sa.inspect(bind).get_columns("business_observations")}
    if "measurement_fingerprint" not in observation_columns:
        op.add_column(
            "business_observations",
            sa.Column("measurement_fingerprint", sa.String(length=128), nullable=True),
        )
        op.create_index(
            "ix_business_observations_measurement_fingerprint",
            "business_observations",
            ["measurement_fingerprint"],
        )
    measurement_constraints = {
        item["name"] for item in sa.inspect(bind).get_unique_constraints("business_measurements")
    }
    if "uq_business_measurements_ingestion_identity" not in measurement_constraints:
        op.create_unique_constraint(
            "uq_business_measurements_ingestion_identity",
            "business_measurements",
            ["tenant_id", "source_content_fingerprint"],
        )
    bind.execute(sa.text("ALTER TABLE business_measurements ENABLE ROW LEVEL SECURITY"))
    bind.execute(sa.text("ALTER TABLE business_measurements FORCE ROW LEVEL SECURITY"))
    bind.execute(
        sa.text(
            "CREATE POLICY tenant_business_measurements_isolation ON business_measurements "
            "AS PERMISSIVE FOR ALL TO PUBLIC "
            "USING (tenant_id = current_setting('app.current_tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))"
        )
    )
    bind.execute(
        sa.text(
            "CREATE POLICY admin_bypass ON business_measurements AS PERMISSIVE FOR ALL TO ajenda_admin "
            "USING (true) WITH CHECK (true)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DROP POLICY IF EXISTS admin_bypass ON business_measurements"))
    bind.execute(sa.text("DROP POLICY IF EXISTS tenant_business_measurements_isolation ON business_measurements"))
    op.drop_constraint("uq_business_measurements_ingestion_identity", "business_measurements", type_="unique")
    op.drop_index("ix_business_observations_measurement_fingerprint", table_name="business_observations")
    op.drop_column("business_observations", "measurement_fingerprint")
    op.drop_index("ix_business_measurements_tenant_id", table_name="business_measurements")
    op.drop_table("business_measurements")
