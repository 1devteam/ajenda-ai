"""Restrict pre-tenant authentication records to the API identity.

Revision ID: 0053_restrict_auth_runtime
Revises: 0052_db_role_separation
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0053_restrict_auth_runtime"
down_revision = "0052_db_role_separation"
branch_labels = None
depends_on = None

# These records are intentionally not subject to ordinary tenant RLS: they
# support pre-tenant OIDC, password login, session refresh, and signup abuse
# control. Only the API owns those workflows. Workers and assurance have no
# source-backed reason to read or mutate them.
_PRE_TENANT_AUTH_TABLES = (
    "customer_auth_sessions",
    "oidc_login_intents",
    "signup_attempt_log",
    "tenant_members",
)
_NON_API_RUNTIME_ROLES = ("ajenda_worker", "ajenda_assurance")


def upgrade() -> None:
    connection = op.get_bind()
    for table in _PRE_TENANT_AUTH_TABLES:
        for role in _NON_API_RUNTIME_ROLES:
            connection.execute(sa.text(f"REVOKE ALL ON TABLE public.{table} FROM {role}"))


def downgrade() -> None:
    """Preserve least privilege during schema rollback.

    Reintroducing worker or assurance access to authentication material would
    be a security regression and is not required for compatibility with an
    earlier schema revision. Forward recovery remains the supported path.
    """
