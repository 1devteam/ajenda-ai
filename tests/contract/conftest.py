"""Contract suite fixtures.

Contract API tests with local dependency overrides must remain runnable without
Docker/Testcontainers. Real Postgres/Redis fixtures are opt-in here so only
contract tests that explicitly request them are skipped when Docker support is
unavailable in the local environment.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy.orm import Session

from tests.integration import conftest as integration_fixtures


@pytest.fixture(scope="session")
def postgres_container() -> Generator[Any, None, None]:
    yield from integration_fixtures.postgres_container.__wrapped__()  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def redis_container() -> Generator[Any, None, None]:
    yield from integration_fixtures.redis_container.__wrapped__()  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def pg_url(postgres_container: Any) -> str:
    return integration_fixtures.pg_url.__wrapped__(postgres_container)  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def redis_url(redis_container: Any) -> str:
    return integration_fixtures.redis_url.__wrapped__(redis_container)  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def integration_env(pg_url: str, redis_url: str) -> Generator[None, None, None]:
    yield from integration_fixtures.integration_env.__wrapped__(pg_url, redis_url)  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def pg_engine(pg_url: str, integration_env: None):
    yield from integration_fixtures.pg_engine.__wrapped__(pg_url, integration_env)  # type: ignore[attr-defined]


@pytest.fixture()
def pg_session(pg_engine) -> Generator[Session, None, None]:
    yield from integration_fixtures.pg_session.__wrapped__(pg_engine)  # type: ignore[attr-defined]


@pytest.fixture()
def redis_client(redis_url: str):
    yield from integration_fixtures.redis_client.__wrapped__(redis_url)  # type: ignore[attr-defined]


@pytest.fixture()
def queue_adapter(integration_env: None):
    yield from integration_fixtures.queue_adapter.__wrapped__(integration_env)  # type: ignore[attr-defined]
