"""Persist immutable successor measurement-contract claims.

Revision ID: 0061_measurement_contract_ref
Revises: 0060_reaffirm_need_rls
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0061_measurement_contract_ref"
down_revision = "0060_reaffirm_need_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("business_measurements")}
    if "intended_measurement_reference" not in columns:
        op.add_column(
            "business_measurements",
            sa.Column("intended_measurement_reference", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("business_measurements")}
    if "intended_measurement_reference" in columns:
        op.drop_column("business_measurements", "intended_measurement_reference")
