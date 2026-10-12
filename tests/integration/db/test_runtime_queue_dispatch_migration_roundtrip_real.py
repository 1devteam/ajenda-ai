from __future__ import annotations

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text

from alembic import command

pytestmark = pytest.mark.integration


def test_runtime_queue_dispatch_migration_round_trip(pg_engine, pg_url: str) -> None:  # type: ignore[no-untyped-def]
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", pg_url)

    command.downgrade(config, "0049_continuous_assurance")
    try:
        assert inspect(pg_engine).has_table("runtime_queue_dispatches") is False

        command.upgrade(config, "head")

        assert inspect(pg_engine).has_table("runtime_queue_dispatches") is True
        with pg_engine.connect() as connection:
            rls = connection.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE oid = 'runtime_queue_dispatches'::regclass"
                )
            ).one()
            policies = set(
                connection.execute(
                    text(
                        "SELECT policyname FROM pg_policies "
                        "WHERE schemaname = current_schema() AND tablename = 'runtime_queue_dispatches'"
                    )
                ).scalars()
            )
        assert rls == (True, True)
        assert policies == {"admin_bypass", "tenant_runtime_queue_dispatch_isolation"}
    finally:
        command.upgrade(config, "head")
