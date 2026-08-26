from pathlib import Path


MIGRATION_PATH = Path("alembic/versions/0043_rebalance_pricing_tier_capacity.py")


def test_pricing_tier_capacity_migration_is_chained_to_current_head() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert 'revision = "0043_pricing_tier_capacity"' in migration
    assert 'down_revision = "0042_http_idempotency"' in migration


def test_pricing_tier_capacity_migration_declares_new_and_previous_contracts() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    for expected in (
        '"free": (25, 500, 2, 1, 2, 5_000)',
        '"starter": (100, 5_000, 5, 3, 5, 50_000)',
        '"pro": (500, 50_000, 25, 10, 20, 500_000)',
        '"enterprise": (-1, -1, -1, -1, -1, -1)',
        '"free": (10, 100, 2, 1, 2, 1_000)',
        '"starter": (25, 500, 5, 3, 5, 25_000)',
        '"pro": (100, 5_000, 20, 10, 20, 250_000)',
    ):
        assert expected in migration

    assert "_apply_limits(_NEW_LIMITS)" in migration
    assert "_apply_limits(_OLD_LIMITS)" in migration


def test_pricing_tier_capacity_migration_does_not_rewrite_feature_entitlements() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "features_enabled" not in migration
    assert "STRIPE_PRICE" not in migration
