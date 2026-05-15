from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_api_key_migration_has_single_head_and_short_revision_id() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    assert heads == ["0019_harden_retrieval_values"]
    assert len(heads[0]) <= 32


def test_api_key_record_migration_matches_orm_security_fields() -> None:
    migration = Path("alembic/versions/0002_add_api_key_records.py").read_text(encoding="utf-8")
    model = Path("backend/domain/api_key_record.py").read_text(encoding="utf-8")

    assert "hashed_secret" in migration
    assert "String(length=256)" in migration
    assert "hashed_secret: Mapped[str] = mapped_column(String(256), nullable=False)" in model
    assert "updated_at" in migration
    assert "updated_at: Mapped[datetime | None]" in model
    assert "revoked_at" in migration
