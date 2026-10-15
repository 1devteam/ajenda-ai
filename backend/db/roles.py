"""PostgreSQL authority names and runtime identity validation.

The values in this module are database *roles*, not application RBAC roles.
They deliberately keep migration authority out of every long-running Ajenda
process.  Configuration validates the connection username before a process
starts; PostgreSQL grants and RLS remain the enforcing boundary.
"""

from __future__ import annotations

from sqlalchemy.engine import make_url

MIGRATOR_ROLE = "ajenda_migrator"
API_ROLE = "ajenda_api"
WORKER_ROLE = "ajenda_worker"
ASSURANCE_ROLE = "ajenda_assurance"

RUNTIME_ROLE_BY_IDENTITY = {
    "api": API_ROLE,
    "worker": WORKER_ROLE,
    "assurance": ASSURANCE_ROLE,
    "migrator": MIGRATOR_ROLE,
}


def database_url_username(database_url: str) -> str:
    """Return the configured username without exposing password material."""
    username = make_url(database_url).username
    if not username:
        raise ValueError("database URL must include a PostgreSQL username")
    return username


def validate_database_identity(*, database_url: str, identity: str, environment: str) -> None:
    """Fail closed when a managed process has the wrong database authority.

    Development and tests can use ephemeral PostgreSQL users, but an explicit
    production-like process identity must always match its least-privilege
    role.  This prevents an otherwise healthy container from silently running
    under the bootstrap or migration identity.
    """
    expected_role = RUNTIME_ROLE_BY_IDENTITY.get(identity)
    if expected_role is None:
        if environment in {"staging", "production"}:
            raise ValueError(
                "AJENDA_DATABASE_IDENTITY must be one of api, worker, assurance, or migrator outside development/test"
            )
        return

    actual_role = database_url_username(database_url)
    if actual_role != expected_role:
        raise ValueError(
            f"database identity {identity!r} must connect as {expected_role!r}; configured username is {actual_role!r}"
        )
