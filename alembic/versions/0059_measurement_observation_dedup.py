"""Deduplicate measurement-derived observations under concurrent ingestion.

Revision ID: 0059_measurement_obs_dedup
Revises: 0058_measurement_security
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0059_measurement_obs_dedup"
down_revision = "0058_measurement_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_business_observations_measurement_identity",
        "business_observations",
        ["tenant_id", "source_fingerprint", "measurement_fingerprint"],
        unique=True,
        postgresql_where=sa.text("measurement_fingerprint IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_business_observations_measurement_identity", table_name="business_observations")
