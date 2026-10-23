"""Persist tenant-scoped business observations and need revisions.

Revision ID: 0055_business_understanding
Revises: 0054_merge_roles_evidence
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0055_business_understanding"
down_revision = "0054_merge_roles_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("source_kind", sa.String(length=48), nullable=False),
        sa.Column("source_reference", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("producer", sa.String(length=160), nullable=False),
        sa.Column("subject_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("observation_summary", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("limitations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("contradicts_observation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("corrects_observation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_business_observations_confidence",
        ),
        sa.CheckConstraint(
            "source_kind IN ('business_profile', 'tenant_internal_record', 'evidence', "
            "'outcome_review', 'knowledge_artifact', 'external_provider', 'customer_instruction')",
            name="ck_business_observations_source_kind",
        ),
    )
    op.create_index("ix_business_observations_tenant_observed", "business_observations", ["tenant_id", "observed_at"])

    op.create_table(
        "business_need_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("need_id", sa.String(length=128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("previous_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="recognized"),
        sa.Column("subject_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("objective_reference", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("condition_summary", sa.Text(), nullable=False),
        sa.Column("uncertainty", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("priority", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("observation_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("related_need_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("candidate_responses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("proposal_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("mission_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("impact_assessment", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("resolution_observation_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("producer", sa.String(length=160), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "id", name="uq_business_need_revisions_tenant_id"),
        sa.UniqueConstraint("tenant_id", "need_id", "revision", name="uq_business_need_revisions_tenant_need_revision"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "previous_revision_id"],
            ["business_need_revisions.tenant_id", "business_need_revisions.id"],
            name="fk_business_need_revisions_previous_tenant",
        ),
        sa.CheckConstraint(
            "status IN ('recognized', 'monitoring', 'challenged', 'response_proposed', "
            "'impact_monitored', 'resolved', 'disproven', 'superseded')",
            name="ck_business_need_revisions_status",
        ),
        sa.CheckConstraint(
            "origin IN ('explicitly_stated', 'observed', 'inferred')",
            name="ck_business_need_revisions_origin",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_business_need_revisions_confidence",
        ),
    )
    op.create_index("ix_business_need_revisions_tenant_need", "business_need_revisions", ["tenant_id", "need_id"])
    bind = op.get_bind()
    for table in ("business_observations", "business_need_revisions"):
        bind.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        bind.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        bind.execute(
            sa.text(
                f"CREATE POLICY tenant_business_understanding_isolation ON {table} "
                "AS PERMISSIVE FOR ALL TO PUBLIC "
                "USING (tenant_id = current_setting('app.current_tenant_id', true)) "
                "WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))"
            )
        )
        bind.execute(
            sa.text(
                f"CREATE POLICY admin_bypass ON {table} AS PERMISSIVE FOR ALL TO ajenda_admin "
                "USING (true) WITH CHECK (true)"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("business_need_revisions", "business_observations"):
        bind.execute(sa.text(f"DROP POLICY IF EXISTS tenant_business_understanding_isolation ON {table}"))
        bind.execute(sa.text(f"DROP POLICY IF EXISTS admin_bypass ON {table}"))
        bind.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
    op.drop_index("ix_business_need_revisions_tenant_need", table_name="business_need_revisions")
    op.drop_table("business_need_revisions")
    op.drop_index("ix_business_observations_tenant_observed", table_name="business_observations")
    op.drop_table("business_observations")
