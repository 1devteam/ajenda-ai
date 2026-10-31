"""Integration test fixtures providing real Postgres and Redis containers.

Schema is created via Alembic migrations, not SQLAlchemy metadata, so
integration tests exercise the same database contract that CI validates in the
migration round-trip job.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path
from secrets import token_urlsafe
from typing import Any

import pytest
from alembic.config import Config as AlembicConfig
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command as alembic_command
from backend.app.config import get_settings
from backend.queue import build_queue_adapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_ROLE_PASSWORD_ENV = {
    "ajenda_migrator": "AJENDA_TEST_MIGRATOR_DATABASE_PASSWORD",
    "ajenda_api": "AJENDA_TEST_API_DATABASE_PASSWORD",
    "ajenda_worker": "AJENDA_TEST_WORKER_DATABASE_PASSWORD",
    "ajenda_assurance": "AJENDA_TEST_ASSURANCE_DATABASE_PASSWORD",
}

# Apply safe integration-test defaults at collection time so modules that
# import backend.main during test discovery do not evaluate production-style
# settings before fixtures have a chance to run.
_COLLECTION_ENV_DEFAULTS = {
    "AJENDA_ENV": "test",
    "AJENDA_LOG_LEVEL": "WARNING",
    "AJENDA_LOG_JSON": "false",
    "AJENDA_APP_NAME": "Ajenda AI Test",
    "AJENDA_OIDC_ISSUER": "",
    "AJENDA_OIDC_AUDIENCE": "ajenda-api",
    "AJENDA_QUEUE_ADAPTER": "local",
    "AJENDA_RATE_LIMIT_REQUESTS": "10000",
    "AJENDA_RATE_LIMIT_WINDOW_SECONDS": "60",
    "AJENDA_REDACT_KEYS": "password,secret,token,api_key,authorization,cookie,set-cookie",
    # Never inherit a developer or deployment credential-encryption key into
    # integration tests.  This key lives only for this test process.
    "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    # Database identities must use fresh, process-local credentials.  Fixed
    # credential-shaped test strings are both unsafe as examples and trigger
    # secret scanners despite never reaching a deployed environment.
    **{environment_key: token_urlsafe(32) for environment_key in _ROLE_PASSWORD_ENV.values()},
}

for _key, _value in _COLLECTION_ENV_DEFAULTS.items():
    if _key == "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY":
        os.environ[_key] = _value
    else:
        os.environ.setdefault(_key, _value)
get_settings.cache_clear()


def _testcontainer_classes() -> tuple[type[Any], type[Any]]:
    """Load testcontainer classes only when integration fixtures are requested."""
    docker_module = pytest.importorskip(
        "docker",
        reason="docker SDK not installed. Run: pip install testcontainers[postgres,redis]",
    )
    docker_client = None
    try:
        docker_client = docker_module.from_env()
        docker_client.ping()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Docker daemon unavailable for testcontainers: {exc}")
    finally:
        try:
            if docker_client is not None:
                docker_client.close()
        except Exception:
            pass

    testcontainers_postgres = pytest.importorskip(
        "testcontainers.postgres",
        reason="testcontainers not installed. Run: pip install testcontainers[postgres,redis]",
    )
    testcontainers_redis = pytest.importorskip(
        "testcontainers.redis",
        reason="testcontainers not installed. Run: pip install testcontainers[postgres,redis]",
    )
    return testcontainers_postgres.PostgresContainer, testcontainers_redis.RedisContainer


def _set_env(pg_url: str, redis_url: str) -> dict[str, str | None]:
    keys = {
        **_COLLECTION_ENV_DEFAULTS,
        "AJENDA_DATABASE_URL": pg_url,
        "AJENDA_QUEUE_ADAPTER": "redis",
        "AJENDA_QUEUE_URL": redis_url,
    }
    previous = {key: os.environ.get(key) for key in keys}
    for key, value in keys.items():
        os.environ[key] = value
    get_settings.cache_clear()
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()


def _postgresql_string_literal(value: str) -> str:
    """Render a value for PostgreSQL utility DDL, which cannot bind PASSWORD."""
    return "'" + value.replace("'", "''") + "'"


@pytest.fixture(scope="session")
def postgres_container() -> Generator[Any, None, None]:
    postgres_container_cls, _ = _testcontainer_classes()
    password = f"test-{token_urlsafe(24)}"
    with postgres_container_cls(
        image="postgres:16-alpine",
        username="ajenda_test",
        password=password,
        dbname="ajenda_test",
    ) as pg:
        yield pg


@pytest.fixture(scope="session")
def redis_container() -> Generator[Any, None, None]:
    _, redis_container_cls = _testcontainer_classes()
    with redis_container_cls(image="redis:7-alpine") as redis:
        yield redis


@pytest.fixture(scope="session")
def pg_url(postgres_container: Any) -> str:
    return postgres_container.get_connection_url().replace("psycopg2", "psycopg")


@pytest.fixture(scope="session")
def redis_url(redis_container: Any) -> str:
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}/0"


@pytest.fixture(scope="session", autouse=True)
def integration_env(pg_url: str, redis_url: str) -> Generator[None, None, None]:
    previous = _set_env(pg_url, redis_url)
    try:
        yield
    finally:
        _restore_env(previous)


@pytest.fixture(scope="session")
def pg_engine(pg_url: str, integration_env: None):
    """Create a real Postgres engine and bootstrap schema via Alembic."""
    engine = create_engine(pg_url, pool_pre_ping=True)

    # Migration 0003 creates RLS policies for the ajenda_admin role, so the role
    # must exist before Alembic upgrades run.
    with engine.begin() as conn:
        conn.execute(
            text(
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

    alembic_cfg = AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", pg_url)

    # Revision 0052 establishes least-privilege runtime roles.  Exercise the
    # same two-step transition used by an existing deployment: migrate through
    # 0051 with the bootstrap administrator, transfer ownership, then let the
    # authorized migrator revision grant runtime access.
    alembic_command.upgrade(alembic_cfg, "0051_billing_meter_dispatches")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ajenda_migrator') THEN
                        CREATE ROLE ajenda_migrator LOGIN NOSUPERUSER NOBYPASSRLS;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ajenda_api') THEN
                        CREATE ROLE ajenda_api LOGIN NOSUPERUSER NOBYPASSRLS;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ajenda_worker') THEN
                        CREATE ROLE ajenda_worker LOGIN NOSUPERUSER NOBYPASSRLS;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ajenda_assurance') THEN
                        CREATE ROLE ajenda_assurance LOGIN NOSUPERUSER NOBYPASSRLS;
                    END IF;
                END
                $$;
                """
            )
        )
        for role, environment_key in _ROLE_PASSWORD_ENV.items():
            password_literal = _postgresql_string_literal(os.environ[environment_key])
            conn.execute(text(f"ALTER ROLE {role} PASSWORD {password_literal}"))
        tables = conn.execute(
            text(
                "SELECT quote_ident(c.relname) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r'"
            )
        ).scalars()
        for table in tables:
            conn.execute(text(f"ALTER TABLE public.{table} OWNER TO ajenda_migrator"))
        conn.execute(text("ALTER SCHEMA public OWNER TO ajenda_migrator"))

    # The release contract requires every revision after the ownership handoff
    # to run through the dedicated migrator identity.  Keeping the bootstrap
    # engine for this step would make later tables appear correctly migrated
    # while assigning their ownership to the test bootstrap role.
    # ``str(URL)`` deliberately redacts a password as ``***``; Alembic needs
    # the actual ephemeral fixture credential for this real login.
    migrator_url = (
        make_url(pg_url)
        .set(username="ajenda_migrator", password=os.environ[_ROLE_PASSWORD_ENV["ajenda_migrator"]])
        .render_as_string(hide_password=False)
    )
    previous_database_url = os.environ.get("AJENDA_DATABASE_URL")
    os.environ["AJENDA_DATABASE_URL"] = migrator_url
    try:
        alembic_command.upgrade(alembic_cfg, "head")
    finally:
        if previous_database_url is None:
            os.environ.pop("AJENDA_DATABASE_URL", None)
        else:
            os.environ["AJENDA_DATABASE_URL"] = previous_database_url
        get_settings.cache_clear()

    from backend.db.vector_schema import ensure_vector_schema

    ensure_vector_schema(engine)

    yield engine
    engine.dispose()


@pytest.fixture()
def transfer_public_table_ownership_to_migrator(pg_engine):
    """Model the explicit bootstrap step required before revision 0052."""

    def transfer() -> None:
        with pg_engine.begin() as connection:
            tables = connection.execute(
                text(
                    "SELECT quote_ident(c.relname) FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')"
                )
            ).scalars()
            for table in tables:
                connection.execute(text(f"ALTER TABLE public.{table} OWNER TO ajenda_migrator"))
            connection.execute(text("ALTER SCHEMA public OWNER TO ajenda_migrator"))

    return transfer


@pytest.fixture()
def pg_session(pg_engine) -> Generator[Session, None, None]:
    """Provide a real Postgres Session that is rolled back after each test."""
    connection = pg_engine.connect()
    transaction = connection.begin()

    session_factory = sessionmaker(
        bind=connection,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    session = session_factory()

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture()
def redis_client(redis_url: str):
    import redis as redis_lib

    client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    yield client
    client.flushdb()
    client.close()


@pytest.fixture()
def queue_adapter(integration_env: None):
    settings = get_settings()
    adapter = build_queue_adapter(settings)
    yield adapter
