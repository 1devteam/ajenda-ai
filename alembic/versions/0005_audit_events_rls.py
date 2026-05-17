"""Add row-level security policy for audit_events.

Revision ID: 0005_audit_events_rls
Revises: 0004_row_level_security
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005_audit_events_rls"
down_revision = "0004_row_level_security"
branch_labels = None
depends_on = None

_TABLE_NAME = "audit_events"


def upgrade() -> None:
    conn = op.get_bind()

    if conn.dialect.name != "postgresql":
        return

    conn.execute(sa.text(f"ALTER TABLE {_TABLE_NAME} ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text(f"ALTER TABLE {_TABLE_NAME} FORCE ROW LEVEL SECURITY"))
    conn.execute(
        sa.text(
            f"""
            CREATE POLICY tenant_isolation ON {_TABLE_NAME}
                AS PERMISSIVE
                FOR ALL
                TO PUBLIC
                USING (
                    tenant_id = current_setting('app.current_tenant_id', true)
                )
                WITH CHECK (
                    tenant_id = current_setting('app.current_tenant_id', true)
                )
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    if conn.dialect.name != "postgresql":
        return

    conn.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation ON {_TABLE_NAME}"))
    conn.execute(sa.text(f"ALTER TABLE {_TABLE_NAME} DISABLE ROW LEVEL SECURITY"))
