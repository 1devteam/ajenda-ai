from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_business_understanding_migration_is_current_head_and_short_revision_id() -> None:
    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()

    assert heads == ["0055_business_understanding"]
    assert len(heads[0]) <= 32


def test_business_understanding_migration_persists_append_only_tenant_contracts() -> None:
    migration = Path("alembic/versions/0055_business_understanding.py").read_text(encoding="utf-8")

    assert "business_observations" in migration
    assert "business_need_revisions" in migration
    assert "uq_business_need_revisions_tenant_need_revision" in migration
    assert "previous_revision_id" in migration
    assert 'sa.Column("producer", sa.String(length=160), nullable=False)' in migration
    assert "observation_references" in migration
    assert "resolution_observation_references" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "tenant_business_understanding_isolation" in migration
    assert "def downgrade" in migration
