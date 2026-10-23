"""Make identical assessment retries atomic at the database boundary.

Revision ID: 0057_assessment_retry_dedup
Revises: 0056_business_need_assessments
"""

from __future__ import annotations

from alembic import op

revision = "0057_assessment_retry_dedup"
down_revision = "0056_business_need_assessments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "business_observations",
        sa.Column("measurement_fingerprint", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_business_observations_measurement_fingerprint",
        "business_observations",
        ["measurement_fingerprint"],
    )
    op.create_unique_constraint(
        "uq_business_need_assessments_retry",
        "business_need_assessments",
        ["tenant_id", "need_id", "need_revision", "assessment_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index("ix_business_observations_measurement_fingerprint", table_name="business_observations")
    op.drop_column("business_observations", "measurement_fingerprint")
    op.drop_constraint("uq_business_need_assessments_retry", "business_need_assessments", type_="unique")
