"""Force tenant isolation for audit events.

Revision ID: 0064_force_audit_event_rls
Revises: 0063_evidence_logical_identity
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0064_force_audit_event_rls"
down_revision = "0063_evidence_logical_identity"
branch_labels = None
depends_on = None

_POLICY = "tenant_audit_event_isolation"


def upgrade() -> None:
    bind = op.get_bind()
    if "audit_events" not in sa.inspect(bind).get_table_names():
        return
    bind.execute(sa.text("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY"))
    bind.execute(sa.text("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY"))
    bind.execute(sa.text(f"DROP POLICY IF EXISTS {_POLICY} ON audit_events"))
    bind.execute(
        sa.text(
            f"""
            CREATE POLICY {_POLICY} ON audit_events
                AS PERMISSIVE
                FOR ALL
                TO PUBLIC
                USING (tenant_id::text = current_setting('app.current_tenant_id', true))
                WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "audit_events" not in sa.inspect(bind).get_table_names():
        return
    bind.execute(sa.text(f"DROP POLICY IF EXISTS {_POLICY} ON audit_events"))
    bind.execute(sa.text("ALTER TABLE audit_events NO FORCE ROW LEVEL SECURITY"))
    bind.execute(sa.text("ALTER TABLE audit_events DISABLE ROW LEVEL SECURITY"))
