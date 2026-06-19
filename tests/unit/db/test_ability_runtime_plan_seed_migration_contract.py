from pathlib import Path


def test_saas_plan_seed_includes_ability_runtime_for_pro_and_enterprise() -> None:
    migration = Path("alembic/versions/0006_add_saas_tenant_tables.py").read_text(encoding="utf-8")
    assert '"ability_runtime"' in migration
    assert migration.index('"ability_runtime"') < migration.index('"gtm"')


def test_ability_runtime_feature_backfill_migration_targets_pro_and_enterprise() -> None:
    migration = Path("alembic/versions/0026_seed_ability_runtime_plan_feature.py").read_text(encoding="utf-8")
    assert "ability_runtime" in migration
    assert "slug IN ('pro', 'enterprise')" in migration
    assert "features_enabled - 'ability_runtime'" in migration
