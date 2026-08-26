from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_tenant_internal_record_migration_is_current_head_and_short_revision_id() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    assert heads == ["0042_http_idempotency"]
    assert len(heads[0]) <= 32


def test_tenant_internal_record_migration_matches_orm_fields() -> None:
    migration = Path("alembic/versions/0033_add_tenant_internal_records.py").read_text(encoding="utf-8")
    model = Path("backend/domain/tenant_internal_record.py").read_text(encoding="utf-8")

    assert "tenant_internal_records" in migration
    assert "record_type" in migration
    assert "data_json" in migration
    assert "search_text" in migration
    assert "TenantInternalRecord" in model
    assert "tenant_internal_records" in model
