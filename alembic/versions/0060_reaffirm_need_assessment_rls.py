"""Reaffirm assessment RLS with graph-observable literal ownership.

Revision ID: 0060_reaffirm_need_rls
Revises: 0059_measurement_obs_dedup
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0060_reaffirm_need_rls"
down_revision = "0059_measurement_obs_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE business_need_assessments ENABLE ROW LEVEL SECURITY"))
    bind.execute(sa.text("ALTER TABLE business_need_assessments FORCE ROW LEVEL SECURITY"))
    bind.execute(
        sa.text(
            """
            DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = current_schema()
                  AND tablename = 'business_need_assessments'
                  AND policyname = 'tenant_business_understanding_isolation'
              ) THEN
                CREATE POLICY tenant_business_understanding_isolation ON business_need_assessments
                  AS PERMISSIVE FOR ALL TO PUBLIC
                  USING (tenant_id = current_setting('app.current_tenant_id', true))
                  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true));
              END IF;
            END $$
            """
        )
    )
    bind.execute(
        sa.text(
            """
            DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = current_schema()
                  AND tablename = 'business_need_assessments'
                  AND policyname = 'admin_bypass'
              ) THEN
                CREATE POLICY admin_bypass ON business_need_assessments
                  AS PERMISSIVE FOR ALL TO ajenda_admin
                  USING (true) WITH CHECK (true);
              END IF;
            END $$
            """
        )
    )


def downgrade() -> None:
    # Migration 0056 owns the policies and RLS lifecycle. This forward repair
    # only makes the already-required enforcement explicit and must not weaken
    # that older boundary when downgraded.
    pass
