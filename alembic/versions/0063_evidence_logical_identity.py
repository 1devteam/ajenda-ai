"""Enforce tenant-scoped logical identity for canonical evidence episodes.

Revision ID: 0063_evidence_logical_identity
Revises: 0062_measurement_pairings
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0063_evidence_logical_identity"
down_revision = "0062_measurement_pairings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("evidence_records")}
    if "logical_identity" not in columns:
        op.add_column("evidence_records", sa.Column("logical_identity", sa.String(length=192), nullable=True))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("evidence_records")}
    if "uq_evidence_records_tenant_logical_identity" not in indexes:
        op.create_index(
            "uq_evidence_records_tenant_logical_identity",
            "evidence_records",
            ["tenant_id", "logical_identity"],
            unique=True,
            postgresql_where=sa.text("logical_identity IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("evidence_records")}
    if "uq_evidence_records_tenant_logical_identity" in indexes:
        op.drop_index("uq_evidence_records_tenant_logical_identity", table_name="evidence_records")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("evidence_records")}
    if "logical_identity" in columns:
        op.drop_column("evidence_records", "logical_identity")
