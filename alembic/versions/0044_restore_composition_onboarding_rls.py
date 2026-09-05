"""Restore tenant RLS on composition and onboarding tables.

Revision ID: 0044_restore_composition_onboarding_rls
Revises: 0043_pricing_tier_capacity
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0044_restore_composition_rls"
down_revision = "0043_pricing_tier_capacity"
branch_labels = None
depends_on = None

_TABLES = (
    "email_send_idempotency_receipts",
    "member_onboarding_preferences",
    "mission_composition_proposals",
    "tenant_onboarding_states",
)


def upgrade() -> None:
    connection = op.get_bind()
    for table in _TABLES:
        connection.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO ajenda_admin"))
        connection.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        connection.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        connection.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation ON {table}
                    AS PERMISSIVE
                    FOR ALL
                    TO PUBLIC
                    USING (tenant_id::text = current_setting('app.current_tenant_id', true))
                    WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
                """
            )
        )
        connection.execute(
            sa.text(
                f"""
                CREATE POLICY admin_bypass ON {table}
                    AS PERMISSIVE
                    FOR ALL
                    TO ajenda_admin
                    USING (true)
                    WITH CHECK (true)
                """
            )
        )


def downgrade() -> None:
    connection = op.get_bind()
    for table in reversed(_TABLES):
        connection.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
        connection.execute(sa.text(f"DROP POLICY IF EXISTS admin_bypass ON {table}"))
        connection.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
