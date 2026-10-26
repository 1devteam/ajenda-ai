"""Persist accepted measurement pairing identities.

Revision ID: 0062_measurement_pairings
Revises: 0061_measurement_contract_ref
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0062_measurement_pairings"
down_revision = "0061_measurement_contract_ref"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("business_measurement_pairings"):
        op.create_table(
            "business_measurement_pairings",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", sa.String(length=128), nullable=False),
            sa.Column("need_id", sa.String(length=128), nullable=False),
            sa.Column("need_revision", sa.Integer(), nullable=False),
            sa.Column("need_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("baseline_measurement_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("observed_measurement_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("successor_contract_id", sa.String(length=128), nullable=True),
            sa.Column("pairing_fingerprint", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="accepted"),
            sa.Column("outcome_evidence_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("outcome_evaluation_id", sa.String(length=160), nullable=True),
            sa.Column("impact_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("producer", sa.String(length=160), nullable=False),
            sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "id", name="uq_business_measurement_pairings_tenant_id"),
            sa.UniqueConstraint("tenant_id", "pairing_fingerprint", name="uq_business_measurement_pairings_retry"),
            sa.UniqueConstraint(
                "tenant_id", "outcome_evidence_id", name="uq_business_measurement_pairings_outcome_evidence"
            ),
            sa.UniqueConstraint(
                "tenant_id", "outcome_evaluation_id", name="uq_business_measurement_pairings_outcome_evaluation"
            ),
            sa.UniqueConstraint(
                "tenant_id", "impact_revision_id", name="uq_business_measurement_pairings_impact_revision"
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "need_revision_id"],
                ["business_need_revisions.tenant_id", "business_need_revisions.id"],
                name="fk_business_measurement_pairings_need_revision_tenant",
            ),
            sa.CheckConstraint("status IN ('accepted', 'evaluated')", name="ck_business_measurement_pairings_status"),
        )
        op.create_index("ix_business_measurement_pairings_tenant_id", "business_measurement_pairings", ["tenant_id"])
        op.create_index(
            "ix_business_measurement_pairings_tenant_need",
            "business_measurement_pairings",
            ["tenant_id", "need_id"],
        )
    bind.execute(sa.text("ALTER TABLE business_measurement_pairings ENABLE ROW LEVEL SECURITY"))
    bind.execute(sa.text("ALTER TABLE business_measurement_pairings FORCE ROW LEVEL SECURITY"))
    bind.execute(
        sa.text(
            "CREATE POLICY tenant_business_measurement_pairings_isolation ON business_measurement_pairings "
            "AS PERMISSIVE FOR ALL TO PUBLIC "
            "USING (tenant_id = current_setting('app.current_tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))"
        )
    )
    bind.execute(
        sa.text(
            "CREATE POLICY admin_bypass ON business_measurement_pairings AS PERMISSIVE FOR ALL TO ajenda_admin "
            "USING (true) WITH CHECK (true)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DROP POLICY IF EXISTS admin_bypass ON business_measurement_pairings"))
    bind.execute(
        sa.text("DROP POLICY IF EXISTS tenant_business_measurement_pairings_isolation ON business_measurement_pairings")
    )
    op.drop_index("ix_business_measurement_pairings_tenant_need", table_name="business_measurement_pairings")
    op.drop_index("ix_business_measurement_pairings_tenant_id", table_name="business_measurement_pairings")
    op.drop_table("business_measurement_pairings")
