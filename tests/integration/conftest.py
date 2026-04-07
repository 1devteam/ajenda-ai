"""Integration test fixtures providing real Postgres and Redis containers.

Uses testcontainers-python to spin up actual database and cache instances
for each test session. This eliminates the SQLite/LocalAdapter mocking that
was masking real behavioral differences (e.g., JSONB vs JSON, UUID types,
RLS policy enforcement, Redis Lua script atomicity).

Container lifecycle:
- Postgres and Redis containers are started once per test session (session scope)
- Schema is created once at session start via Alembic migrations
- Each test gets a fresh database transaction that is rolled back after the test
  (function scope), ensuring test isolation without re-running migrations

Requirements:
- Docker must be available in the test environment
- testcontainers[postgres,redis] must be installed (added to pyproject.toml dev deps)

Environment variables set by these fixtures:
- AJENDA_DATABASE_URL: postgresql+psycopg://... pointing to the test container
- AJENDA_QUEUE_URL: redis://localhost:<port>/0 pointing to the test container

Usage:
    def test_something(pg_session, redis_client):
        # pg_session is a real SQLAlchemy Session against Postgres
        # redis_client is a real redis.Redis client
        ...
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# testcontainers imports — gracefully skip if not installed
pytest.importorskip(
    "testcontainers",
    reason="testcontainers not installed. Run: pip install testcontainers[postgres,redis]",
)

from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from backend.db.base import Base

# ---------------------------------------------------------------------------
# Session-scoped containers — started once, shared across all integration tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_container():
    """Start a real PostgreSQL container for the test session."""
    with PostgresContainer(
        image="postgres:16-alpine",
        username="ajenda_test",
        password="ajenda_test",
        dbname="ajenda_test",
    ) as pg:
        yield pg


@pytest.fixture(scope="session")
def redis_container():
    """Start a real Redis container for the test session."""
    with RedisContainer(image="redis:7-alpine") as redis:
        yield redis


@pytest.fixture(scope="session")
def pg_engine(postgres_container):
    """Create a SQLAlchemy engine connected to the test Postgres container.

    Runs all Alembic migrations once at session start to create the full schema.
    """
    url = postgres_container.get_connection_url().replace(
        "psycopg2",
        "psycopg",  # Use psycopg v3
    )
    engine = create_engine(url, pool_pre_ping=True)

    # Create all tables via SQLAlchemy metadata (faster than running Alembic
    # for tests; Alembic migration tests run separately in tests/integration/db/)
    Base.metadata.create_all(engine)

    # Set the search path and create the ajenda_admin role for RLS bypass
    with engine.connect() as conn:
        conn.execute(text("CREATE ROLE IF NOT EXISTS ajenda_admin"))
        conn.commit()

    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def redis_url(redis_container) -> str:
    """Return the Redis URL for the test container."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}/0"


# ---------------------------------------------------------------------------
# Function-scoped fixtures — fresh transaction per test, rolled back after
# ---------------------------------------------------------------------------


@pytest.fixture()
def pg_session(pg_engine) -> Generator[Session, None, None]:
    """Provide a real Postgres Session that is rolled back after each test.

    This gives each test a clean slate without re-running migrations.
    The SAVEPOINT approach ensures nested transactions work correctly.
    """
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
    """Provide a real Redis client connected to the test container."""
    import redis as redis_lib

    client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    yield client
    # Flush the test database after each test for isolation
    client.flushdb()
    client.close()


@pytest.fixture()
def queue_adapter(redis_url: str):
    """Provide a real RedisQueueAdapter connected to the test container."""
    from backend.app.config import Settings
    from backend.queue import build_queue_adapter

    settings = Settings.model_construct(
        database_url="postgresql+psycopg://ajenda_test:ajenda_test@localhost/ajenda_test",
        env="test",
        queue_adapter="redis",
        queue_url=redis_url,
        port=8000,
        log_json=False,
        rate_limit_requests=1000,
        rate_limit_window_seconds=60,
    )
    adapter = build_queue_adapter(settings)
    yield adapter


# ---------------------------------------------------------------------------
# Environment variable injection for tests that use Settings directly
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=False)
def inject_test_env(postgres_container, redis_url, monkeypatch):
    """Inject test container URLs into environment variables.

    Use this fixture in tests that instantiate Settings() directly.
    """
    pg_url = postgres_container.get_connection_url().replace("psycopg2", "psycopg")
    monkeypatch.setenv("AJENDA_DATABASE_URL", pg_url)
    monkeypatch.setenv("AJENDA_QUEUE_URL", redis_url)
    monkeypatch.setenv("AJENDA_QUEUE_ADAPTER", "redis")
    monkeypatch.setenv("AJENDA_ENV", "test")
