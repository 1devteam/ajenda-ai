"""Real PostgreSQL proof for Ajenda's restricted runtime database roles."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_urlsafe

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from backend.domain.provider_runtime_credential import ProviderRuntimeCredential
from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector
from backend.services.credentials.sqlalchemy_repository import SQLAlchemyCredentialRuntimeRepository

_ROLE_PASSWORDS = {
    "api": f"test-{token_urlsafe(24)}",
    "worker": f"test-{token_urlsafe(24)}",
    "assurance": f"test-{token_urlsafe(24)}",
    "migrator": f"test-{token_urlsafe(24)}",
}


def _bootstrap_roles(pg_engine) -> None:
    sql = Path("deploy/sql/database_role_bootstrap.sql").read_text(encoding="utf-8")
    # psql client directives are stripped for this direct DBAPI execution.
    sql = "\n".join(line for line in sql.splitlines() if not line.startswith("\\getenv "))

    sql = (
        sql.replace(":'api_password'", f"'{_ROLE_PASSWORDS['api']}'")
        .replace(":'worker_password'", f"'{_ROLE_PASSWORDS['worker']}'")
        .replace(":'assurance_password'", f"'{_ROLE_PASSWORDS['assurance']}'")
        .replace(":'migrator_password'", f"'{_ROLE_PASSWORDS['migrator']}'")
    )
    raw_connection = pg_engine.raw_connection()
    try:
        with raw_connection.cursor() as cursor:
            cursor.execute(sql)
        raw_connection.commit()
    finally:
        raw_connection.close()


def _role_url(pg_url: str, *, username: str, password: str) -> URL:
    url = make_url(pg_url)
    return url.set(username=username, password=password)


def _seed_tenants(pg_engine) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    with pg_engine.begin() as conn:
        for tenant_id, suffix in ((tenant_a, "a"), (tenant_b, "b")):
            conn.execute(
                text("INSERT INTO tenants (id, name, slug, status, plan) VALUES (:id, :name, :slug, 'active', 'free')"),
                {"id": tenant_id, "name": f"Role test {suffix}", "slug": f"role-test-{tenant_id.hex}"},
            )
            conn.execute(
                text(
                    "INSERT INTO billing_meter_dispatches "
                    "(id, tenant_id, metric, quantity, status, attempt_count, next_attempt_at, created_at, updated_at) "
                    "VALUES (:id, :tenant_id, 'missions', 1, 'pending', 0, :now, :now, :now)"
                ),
                {"id": uuid.uuid4(), "tenant_id": tenant_id, "now": now},
            )
    return tenant_a, tenant_b


def _set_tenant(connection, tenant_id: uuid.UUID) -> None:
    connection.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"), {"tenant_id": str(tenant_id)}
    )


def test_runtime_roles_are_restricted_and_billing_rows_are_tenant_isolated_real(pg_engine, pg_url: str) -> None:
    tenant_a, tenant_b = _seed_tenants(pg_engine)
    api_engine = create_engine(_role_url(pg_url, username="ajenda_api", password=_ROLE_PASSWORDS["api"]))
    worker_engine = create_engine(_role_url(pg_url, username="ajenda_worker", password=_ROLE_PASSWORDS["worker"]))
    assurance_engine = create_engine(
        _role_url(pg_url, username="ajenda_assurance", password=_ROLE_PASSWORDS["assurance"])
    )
    try:
        with api_engine.begin() as conn:
            identity = conn.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            ).one()
            assert identity == ("ajenda_api", False, False, False, False)
            _set_tenant(conn, tenant_a)
            assert conn.scalar(text("SELECT count(*) FROM billing_meter_dispatches")) == 1
            assert (
                conn.scalar(
                    text("SELECT count(*) FROM billing_meter_dispatches WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_b},
                )
                == 0
            )
            with pytest.raises(DBAPIError):
                conn.execute(
                    text(
                        "INSERT INTO billing_meter_dispatches "
                        "(id, tenant_id, metric, quantity, status, attempt_count, next_attempt_at) "
                        "VALUES (:id, :tenant_id, 'missions', 1, 'pending', 0, now())"
                    ),
                    {"id": uuid.uuid4(), "tenant_id": tenant_b},
                )

        with api_engine.begin() as conn:
            # SET LOCAL state ends with the transaction; pooled connections
            # therefore cannot carry Tenant A into a no-context request.
            assert conn.scalar(text("SELECT count(*) FROM billing_meter_dispatches")) == 0

        with api_engine.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM tenant_members")) == 0

        for engine in (worker_engine, assurance_engine):
            with engine.connect() as conn:
                for table in (
                    "customer_auth_sessions",
                    "oidc_login_intents",
                    "signup_attempt_log",
                    "tenant_members",
                ):
                    with pytest.raises(DBAPIError):
                        conn.execute(text(f"SELECT count(*) FROM {table}"))
                    conn.rollback()

        for engine in (api_engine, worker_engine):
            with engine.connect() as conn:
                for statement in (
                    "CREATE TABLE runtime_role_escape (id integer)",
                    "ALTER TABLE billing_meter_dispatches DISABLE ROW LEVEL SECURITY",
                    "CREATE ROLE runtime_role_escape",
                ):
                    with pytest.raises(DBAPIError):
                        conn.execute(text(statement))
                    conn.rollback()

        with assurance_engine.begin() as conn:
            _set_tenant(conn, tenant_a)
            assert conn.scalar(text("SELECT count(*) FROM billing_meter_dispatches")) == 1
            with pytest.raises(DBAPIError):
                conn.execute(
                    text("UPDATE billing_meter_dispatches SET status = 'delivered' WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_a},
                )
    finally:
        api_engine.dispose()
        worker_engine.dispose()
        assurance_engine.dispose()


def test_worker_credential_runtime_repository_activates_tenant_rls_context_real(pg_engine, pg_url: str) -> None:
    """A fresh worker lookup must activate RLS before resolving a credential."""

    tenant_a, tenant_b = _seed_tenants(pg_engine)
    credential_id = f"credential-{uuid.uuid4().hex}"
    protector = RuntimeCredentialSecretProtector()
    with Session(pg_engine) as setup:
        setup.add(
            ProviderRuntimeCredential(
                id=f"prc-{uuid.uuid4()}",
                tenant_id=str(tenant_a),
                credential_id=credential_id,
                provider="external_crm",
                integration="hubspot",
                credential_type="api_key",
                enabled=True,
                revoked=False,
                deleted=False,
                allowed_actions=["crm.read"],
                allowed_side_effect_classes=["external_read"],
                trusted_destination_hosts=["api.hubapi.com"],
                secret_ciphertext=protector.encrypt_secret("worker-rls-test-secret"),
            )
        )
        setup.commit()

    worker_engine = create_engine(_role_url(pg_url, username="ajenda_worker", password="integration-worker"))
    worker_factory = sessionmaker(bind=worker_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    try:
        repository = SQLAlchemyCredentialRuntimeRepository(session_factory=worker_factory)
        record = repository.get_visible_for_tenant(tenant_id=str(tenant_a), credential_id=credential_id)
        assert record is not None
        assert record.tenant_id == str(tenant_a)
        assert record.credential_id == credential_id
        assert repository.get_visible_for_tenant(tenant_id=str(tenant_b), credential_id=credential_id) is None
    finally:
        worker_engine.dispose()


def test_bootstrap_hardens_existing_runtime_roles_and_removes_memberships_real(pg_engine) -> None:
    with pg_engine.begin() as connection:
        connection.execute(text("CREATE ROLE stale_privileged NOLOGIN SUPERUSER BYPASSRLS CREATEROLE"))
        connection.execute(text("ALTER ROLE ajenda_worker SUPERUSER BYPASSRLS CREATEROLE CREATEDB INHERIT"))
        connection.execute(text("GRANT stale_privileged TO ajenda_worker"))

    _bootstrap_roles(pg_engine)

    with pg_engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolinherit "
                "FROM pg_roles WHERE rolname = 'ajenda_worker'"
            )
        ).one()
        assert role == (False, False, False, False, False)
        membership_count = connection.scalar(
            text(
                "SELECT count(*) FROM pg_auth_members membership "
                "JOIN pg_roles member ON member.oid = membership.member "
                "WHERE member.rolname = 'ajenda_worker'"
            )
        )
        assert membership_count == 0
