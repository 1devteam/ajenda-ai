"""Separate Ajenda runtime identities from database administration.

Revision ID: 0052_db_role_separation
Revises: 0051_billing_meter_dispatches
"""

from __future__ import annotations

import re

import sqlalchemy as sa

from alembic import op

revision = "0052_db_role_separation"
down_revision = "0051_billing_meter_dispatches"
branch_labels = None
depends_on = None

_RUNTIME_ROLES = ("ajenda_api", "ajenda_worker", "ajenda_assurance")
_MIGRATOR_ROLE = "ajenda_migrator"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quoted_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise RuntimeError(f"unexpected PostgreSQL identifier {value!r}")
    return f'"{value}"'


def _require_roles(connection: sa.Connection) -> None:
    rows = connection.execute(
        sa.text(
            "SELECT rolname FROM pg_roles "
            "WHERE rolname = ANY(ARRAY['ajenda_migrator', 'ajenda_api', 'ajenda_worker', 'ajenda_assurance'])"
        )
    ).scalars()
    missing = sorted(set((_MIGRATOR_ROLE, *_RUNTIME_ROLES)).difference(rows))
    if missing:
        raise RuntimeError(
            "database role bootstrap has not completed; missing "
            f"{', '.join(missing)}. Run deploy/scripts/provision-database-roles.sh with an authorized bootstrap role."
        )


def _public_tables(connection: sa.Connection) -> list[str]:
    return list(
        connection.execute(
            sa.text(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
                "ORDER BY c.relname"
            )
        ).scalars()
    )


def upgrade() -> None:
    connection = op.get_bind()
    _require_roles(connection)
    tables = _public_tables(connection)

    # Runtime identities never own tables.  The bootstrap procedure transfers
    # existing ownership before this revision; this assertion prevents a
    # partial transition from appearing successful.
    for table in tables:
        quoted_table = _quoted_identifier(table)
        owner = connection.execute(
            sa.text(
                "SELECT pg_get_userbyid(c.relowner) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = :table"
            ),
            {"table": table},
        ).scalar_one()
        if owner != _MIGRATOR_ROLE:
            raise RuntimeError(
                f"{table} is owned by {owner!r}; bootstrap ownership transfer to {_MIGRATOR_ROLE!r} is required"
            )
        connection.execute(sa.text(f"DROP POLICY IF EXISTS admin_bypass ON public.{quoted_table}"))

    connection.execute(sa.text("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC"))
    connection.execute(sa.text("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC"))
    connection.execute(sa.text("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ajenda_admin"))
    connection.execute(sa.text("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM ajenda_admin"))
    connection.execute(sa.text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
    connection.execute(sa.text("REVOKE ALL ON SCHEMA public FROM ajenda_admin"))

    for role in ("ajenda_api", "ajenda_worker"):
        connection.execute(sa.text(f"GRANT USAGE ON SCHEMA public TO {role}"))
        connection.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}"))
        connection.execute(sa.text(f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {role}"))

    # Assurance evaluates canonical state but can mutate only its own
    # read-model outputs and aggregate metrics.
    connection.execute(sa.text("GRANT USAGE ON SCHEMA public TO ajenda_assurance"))
    connection.execute(sa.text("GRANT SELECT ON ALL TABLES IN SCHEMA public TO ajenda_assurance"))
    connection.execute(
        sa.text("GRANT INSERT, UPDATE ON TABLE assurance_snapshots, assurance_metric_state TO ajenda_assurance")
    )

    for role in ("ajenda_api", "ajenda_worker"):
        connection.execute(
            sa.text(
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {_MIGRATOR_ROLE} IN SCHEMA public "
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}"
            )
        )
        connection.execute(
            sa.text(
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {_MIGRATOR_ROLE} IN SCHEMA public "
                f"GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {role}"
            )
        )
    connection.execute(
        sa.text(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {_MIGRATOR_ROLE} IN SCHEMA public "
            "GRANT SELECT ON TABLES TO ajenda_assurance"
        )
    )


def downgrade() -> None:
    """Remove grants introduced by this revision without restoring privilege.

    The schema downgrade chain must remain executable for CI and for verified
    rollback rehearsal.  Reversing this revision must *not* make an older
    application release run as a table owner, a superuser, or an RLS-bypass
    role.  The bootstrap administrator retains responsibility for recovery
    access; runtime roles lose the grants this revision added.
    """
    connection = op.get_bind()
    _require_roles(connection)

    for role in _RUNTIME_ROLES:
        connection.execute(sa.text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}"))
        connection.execute(sa.text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role}"))
        connection.execute(sa.text(f"REVOKE USAGE ON SCHEMA public FROM {role}"))

    for role in _RUNTIME_ROLES:
        connection.execute(
            sa.text(
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {_MIGRATOR_ROLE} IN SCHEMA public "
                f"REVOKE ALL ON TABLES FROM {role}"
            )
        )
        connection.execute(
            sa.text(
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {_MIGRATOR_ROLE} IN SCHEMA public "
                f"REVOKE ALL ON SEQUENCES FROM {role}"
            )
        )
