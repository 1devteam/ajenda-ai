from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_business_profile_migration_is_current_head_and_short_revision_id() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    assert heads == ["0026_seed_ability_runtime"]
    assert len(heads[0]) <= 32


def test_business_profile_migration_contains_profile_and_suggestion_contracts() -> None:
    migration = Path("alembic/versions/0022_add_business_profiles.py").read_text(encoding="utf-8")

    assert "business_profiles" in migration
    assert "business_profile_suggestions" in migration
    assert "approved_facts" in migration
    assert "suggested_fact" in migration
    assert "source_context" in migration
    assert "resolution" in migration
    assert "postgresql.JSONB" in migration
    assert "ck_business_profiles_status" in migration
    assert "ck_business_profile_suggestions_status" in migration
    assert "uq_business_profiles_active_tenant" in migration
    assert "ix_business_profile_suggestions_tenant_status" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "tenant_business_profile_isolation" in migration
    assert "tenant_business_profile_suggestion_isolation" in migration
    assert "admin_bypass" in migration
    assert "def downgrade" in migration
