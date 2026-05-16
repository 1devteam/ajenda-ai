"""Contract suite fixture bridge.

Pytest 9 disallows ``pytest_plugins`` in non-top-level conftest files.
Contract tests that need real runtime fixtures can still request them by name,
but the Docker/Testcontainers environment must not be an autouse requirement for
all contract tests. Most contract tests use in-process fakes and should execute
without Docker.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from tests.integration import conftest as integration_fixtures

postgres_container = integration_fixtures.postgres_container
redis_container = integration_fixtures.redis_container
pg_url = integration_fixtures.pg_url
redis_url = integration_fixtures.redis_url
pg_engine = integration_fixtures.pg_engine
pg_session = integration_fixtures.pg_session
redis_client = integration_fixtures.redis_client
queue_adapter = integration_fixtures.queue_adapter


@pytest.fixture(scope="session")
def integration_env(pg_url: str, redis_url: str) -> Generator[None, None, None]:
    """Provide integration env only to contract tests that request it.

    The corresponding fixture in ``tests.integration.conftest`` is autouse for
    the integration suite. Re-declaring it here without autouse prevents
    Docker-backed fixtures from skipping unrelated fake-backed contract tests.
    """
    previous = integration_fixtures._set_env(pg_url, redis_url)
    try:
        yield
    finally:
        integration_fixtures._restore_env(previous)
