from __future__ import annotations

import pytest
from alembic.config import Config
from sqlalchemy import text

from alembic import command

pytestmark = pytest.mark.integration


def test_audit_event_rls_migration_round_trip(  # type: ignore[no-untyped-def]
    pg_engine, pg_url: str, transfer_public_table_ownership_to_migrator
) -> None:
    """The audit boundary must be present after upgrade and removed on downgrade."""

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", pg_url)

    command.downgrade(config, "0063_evidence_logical_identity")
    try:
        with pg_engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT relrowsecurity FROM pg_class WHERE oid = 'audit_events'::regclass")
                ).scalar_one()
                is False
            )

        transfer_public_table_ownership_to_migrator()
        command.upgrade(config, "head")

        with pg_engine.connect() as connection:
            rls = connection.execute(
                text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = 'audit_events'::regclass")
            ).one()
            policies = set(
                connection.execute(
                    text(
                        "SELECT policyname FROM pg_policies "
                        "WHERE schemaname = current_schema() AND tablename = 'audit_events'"
                    )
                ).scalars()
            )

        assert rls == (True, True)
        assert policies == {"tenant_audit_event_isolation"}
    finally:
        command.upgrade(config, "0063_evidence_logical_identity")
        transfer_public_table_ownership_to_migrator()
        command.upgrade(config, "head")
