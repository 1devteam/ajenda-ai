"""Add PostgreSQL row-level security for tenant-scoped tables.

Revision ID: 0004_row_level_security
Revises: 0003_add_recovering_task_state
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004_row_level_security"
down_revision = "0003_add_recovering_task_state"
branch_labels = None
depends_on = None

_TENANT_SCOPED_TABLES: tuple[str, ...] = (
    "missions",
    "execution_tasks",
    "execution_branches",
    "user_workforce_agents",
    "workforce_fleets",
    "worker_leases",
    "lineage_records",
    "governance_events",
    "api_key_records",
)


def upgrade() -> None:
    conn = op.get_bind()

    if conn.dialect.name != "postgresql":
        return

    for table in _TENANT_SCOPED_TABLES:
        conn.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        conn.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        conn.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation ON {table}
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

    for table in _TENANT_SCOPED_TABLES:
        conn.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
        conn.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
