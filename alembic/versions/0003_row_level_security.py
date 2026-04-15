"""Row-Level Security — per-tenant data isolation at the database layer.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-03

Why RLS?
--------
Without RLS, a bug in the application layer (e.g., a missing tenant_id filter
in a repository query) can silently return or mutate another tenant's data.
RLS enforces the isolation guarantee at the PostgreSQL level — even if the
application sends a query without a WHERE tenant_id = ... clause, the database
will only return rows whose tenant_id matches the current session variable
app.current_tenant_id.

How it works:
-------------
1. RLS is enabled on each tenant-scoped table.
2. A PERMISSIVE policy is created that evaluates:
       tenant_id = current_setting('app.current_tenant_id', true)
   The second argument (true) means the function returns NULL (not an error)
   if the variable is not set — which causes the policy to evaluate to FALSE
   and return no rows. This is fail-closed: unset session variable = no data.
3. The application must SET LOCAL app.current_tenant_id = '<tenant_id>'
   at the start of every database transaction that accesses tenant-scoped data.
4. A superuser bypass role (ajenda_admin) is exempted from RLS so that
   migrations, maintenance, and admin tooling continue to work.

Tables covered:
---------------
- missions
- execution_tasks
- execution_branches
- user_workforce_agents
- workforce_fleets
- worker_leases
- lineage_records
- governance_events
- api_key_records

Tables NOT covered (system-wide, no tenant_id):
-----------------------------------------------
- audit_events (cross-tenant audit log — admin access only)
- alembic_version (migration tracking)

Application integration:
------------------------
In backend/db/session.py, session_scope() must be updated to call:
    session.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})
immediately after beginning the transaction. See the companion PR for the
session_scope_for_tenant() method added to DatabaseRuntime.

Rollback safety:
----------------
The down() migration disables RLS and drops all policies. This is safe because
the data itself is not modified — only the access policy is removed.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = "0003_row_level_security"
down_revision = "0002_add_api_key_records"
branch_labels = None
depends_on = None

# Tables that have a tenant_id column and must be RLS-protected
_TENANT_SCOPED_TABLES: list[str] = [
    "missions",
    "execution_tasks",
    "execution_branches",
    "user_workforce_agents",
    "workforce_fleets",
    "worker_leases",
    "lineage_records",
    "governance_events",
    "api_key_records",
]


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = 'ajenda_admin'
                ) THEN
                    CREATE ROLE ajenda_admin;
                END IF;
            END
            $$;
            """
        )
    )
    """Enable Row-Level Security on all tenant-scoped tables."""
    conn = op.get_bind()

    for table in _TENANT_SCOPED_TABLES:
        # Step 1: Enable RLS on the table
        conn.execute(__import__("sqlalchemy").text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))

        # Step 2: Force RLS even for the table owner (prevents owner bypass)
        conn.execute(__import__("sqlalchemy").text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))

        # Step 3: Create the tenant isolation policy
        # current_setting('app.current_tenant_id', true) returns NULL if unset,
        # which causes the comparison to be NULL = tenant_id → FALSE → no rows.
        # This is intentionally fail-closed.
        conn.execute(
            __import__("sqlalchemy").text(f"""
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
            """)
        )

    # Step 4: Create the admin bypass policy for the ajenda_admin role.
    # This allows migrations, maintenance scripts, and admin tooling to
    # access all rows without setting the session variable.
    # The ajenda_admin role must be created separately in the DB provisioning
    # scripts and granted to the migration runner.
    for table in _TENANT_SCOPED_TABLES:
        conn.execute(
            __import__("sqlalchemy").text(f"""
                CREATE POLICY admin_bypass ON {table}
                    AS PERMISSIVE
                    FOR ALL
                    TO ajenda_admin
                    USING (true)
                    WITH CHECK (true)
            """)
        )

    # Step 5: Document the required session variable in a DB comment
    # so future engineers understand the contract.
    conn.execute(
        __import__("sqlalchemy").text("""
            COMMENT ON DATABASE CURRENT IS
            'Ajenda AI: Set app.current_tenant_id session variable before
             querying any tenant-scoped table. RLS enforces isolation.'
        """)
    )


def downgrade() -> None:
    """Disable Row-Level Security and drop all tenant isolation policies."""
    conn = op.get_bind()

    for table in _TENANT_SCOPED_TABLES:
        # Drop policies first, then disable RLS
        conn.execute(__import__("sqlalchemy").text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
        conn.execute(__import__("sqlalchemy").text(f"DROP POLICY IF EXISTS admin_bypass ON {table}"))
        conn.execute(__import__("sqlalchemy").text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
