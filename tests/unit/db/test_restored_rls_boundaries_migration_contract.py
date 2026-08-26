from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_restored_rls_migration_is_single_current_head() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    assert heads == ["0043_pricing_tier_capacity"]
    assert len(heads[0]) <= 32


def test_restored_rls_migration_covers_usage_and_webhook_tables() -> None:
    migration = Path("alembic/versions/0041_restore_tenant_rls_boundaries.py").read_text(encoding="utf-8")

    for table in ("tenant_usage", "webhook_endpoints", "webhook_deliveries"):
        assert table in migration

    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "CREATE POLICY tenant_isolation" in migration
    assert "CREATE POLICY admin_bypass" in migration
    assert "current_setting('app.current_tenant_id', true)" in migration
    assert "tenant_id::text" in migration
    assert "DROP POLICY IF EXISTS tenant_isolation" in migration
    assert "DROP POLICY IF EXISTS admin_bypass" in migration
    assert "DISABLE ROW LEVEL SECURITY" in migration
    assert "def downgrade" in migration
