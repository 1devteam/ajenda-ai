"""Secure and deduplicate authoritative business measurements.

Revision ID: 0058_measurement_security
Revises: 0057_assessment_retry_dedup
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0058_measurement_security"
down_revision = "0057_assessment_retry_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_business_measurements_ingestion_identity",
        "business_measurements",
        ["tenant_id", "source_content_fingerprint"],
    )
    bind = op.get_bind()
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
