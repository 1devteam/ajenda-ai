from pathlib import Path


def test_gtm_catalog_seed_migration_uses_temporary_global_row_policy_for_upgrade_and_downgrade() -> None:
    migration = Path("alembic/versions/0021_seed_gtm_capability_catalog.py").read_text(encoding="utf-8")

    assert "seed_global_gtm_capabilities_policy" in migration
    assert "seed_global_gtm_capability_adapters_policy" in migration
    assert "FOR ALL" in migration
    assert "USING (tenant_id IS NULL)" in migration
    assert "WITH CHECK (tenant_id IS NULL)" in migration
    assert "def upgrade" in migration
    assert "def downgrade" in migration


def test_gtm_catalog_seed_migration_is_cleanup_symmetric() -> None:
    migration = Path("alembic/versions/0021_seed_gtm_capability_catalog.py").read_text(encoding="utf-8")

    assert migration.count("_drop_seed_policy(conn, \"capabilities\", \"seed_global_gtm_capabilities_policy\")") >= 2
    assert migration.count(
        "_drop_seed_policy(conn, \"capability_adapters\", \"seed_global_gtm_capability_adapters_policy\")"
    ) >= 2
    assert "DELETE FROM capability_adapters" in migration
    assert "DELETE FROM capabilities" in migration
