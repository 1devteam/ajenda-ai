from __future__ import annotations

import pytest
from sqlalchemy import text

from backend.db.schema_revision import SchemaRevisionError, verify_schema_revision

pytestmark = pytest.mark.integration


def test_schema_revision_verifier_accepts_head_and_rejects_stale_postgres_record(pg_engine) -> None:  # type: ignore[no-untyped-def]
    """A runtime checks migration state; it never upgrades the database itself."""
    accepted = verify_schema_revision(pg_engine)
    assert accepted.status == "ready"
    assert len(accepted.actual_heads) == 1
    original_revision = accepted.actual_heads[0]

    with pg_engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '0060_reaffirm_need_rls'"))

    try:
        with pytest.raises(SchemaRevisionError, match="behind") as exc_info:
            verify_schema_revision(pg_engine)
        assert exc_info.value.status == "behind"
        assert exc_info.value.actual_heads == ("0060_reaffirm_need_rls",)
    finally:
        with pg_engine.begin() as connection:
            connection.execute(
                text("UPDATE alembic_version SET version_num = :revision"), {"revision": original_revision}
            )

    restored = verify_schema_revision(pg_engine)
    assert restored.status == "ready"
