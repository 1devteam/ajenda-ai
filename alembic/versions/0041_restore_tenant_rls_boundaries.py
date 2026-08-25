"""Restore RLS for tenant usage and webhook persistence surfaces.

Revision ID: 0041_restore_tenant_rls
Revises: 0040_onboarding_connectors
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0041_restore_tenant_rls"
down_revision = "0040_onboarding_connectors"
branch_labels = None
depends_on = None

_TABLES = ("tenant_usage", "webhook_endpoints", "webhook_deliveries")


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
        connection.execute(sa.text(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE {table} FROM ajenda_admin"))
