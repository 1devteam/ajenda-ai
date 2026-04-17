"""Contract suite fixture bridge.

Pytest 9 disallows ``pytest_plugins`` in non-top-level conftest files.
Contract tests still need the real runtime fixtures (Postgres/Redis/session)
defined for integration tests, so we import and re-export them directly.
"""

from tests.integration.conftest import *  # noqa: F403
