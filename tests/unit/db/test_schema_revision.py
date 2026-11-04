from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from backend.db import schema_revision


def _engine_with_revision(*revisions: str):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        for revision in revisions:
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"), {"revision": revision}
            )
    return engine


def test_verify_schema_revision_accepts_exact_single_runtime_head(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine_with_revision("0064_force_audit_event_rls")
    monkeypatch.setattr(schema_revision, "expected_schema_heads", lambda: ("0064_force_audit_event_rls",))

    check = schema_revision.verify_schema_revision(engine)

    assert check.status == "ready"
    assert check.actual_heads == check.expected_heads == ("0064_force_audit_event_rls",)


def test_verify_schema_revision_rejects_stale_database(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine_with_revision("0060_reaffirm_need_rls")
    monkeypatch.setattr(schema_revision, "expected_schema_heads", lambda: ("0064_force_audit_event_rls",))

    with pytest.raises(schema_revision.SchemaRevisionError, match="behind") as exc_info:
        schema_revision.verify_schema_revision(engine)

    assert exc_info.value.status == "behind"
    assert exc_info.value.actual_heads == ("0060_reaffirm_need_rls",)


def test_verify_schema_revision_rejects_missing_revision_table(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite://")
    monkeypatch.setattr(schema_revision, "expected_schema_heads", lambda: ("0064_force_audit_event_rls",))

    with pytest.raises(schema_revision.SchemaRevisionError, match="unavailable") as exc_info:
        schema_revision.verify_schema_revision(engine)

    assert exc_info.value.status == "unavailable"


def test_expected_schema_heads_is_the_repository_single_head() -> None:
    schema_revision.expected_schema_heads.cache_clear()

    assert schema_revision.expected_schema_heads() == ("0064_force_audit_event_rls",)
