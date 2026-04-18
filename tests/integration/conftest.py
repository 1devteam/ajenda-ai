"""Integration test fixtures providing real Postgres and Redis containers.

Schema is created via Alembic migrations, not SQLAlchemy metadata, so
integration tests exercise the same database contract that CI validates in the
migration round-trip job.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from alembic import command as alembic_command
from backend.app.config import get_settings
from backend.queue import build_queue_adapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]

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
}

for _key, _value in _COLLECTION_ENV_DEFAULTS.items():
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


@pytest.fixture(scope="session")
def postgres_container() -> Generator[Any, None, None]:
    postgres_container_cls, _ = _testcontainer_classes()
    with postgres_container_cls(
        image="postgres:16-alpine",
        username="ajenda_test",
        password="ajenda_test",
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

    alembic_command.upgrade(alembic_cfg, "head")

    yield engine
    engine.dispose()


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
