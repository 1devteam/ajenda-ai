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

    assert migration.count('_drop_seed_policy(conn, "capabilities", "seed_global_gtm_capabilities_policy")') >= 2
    assert (
        migration.count('_drop_seed_policy(conn, "capability_adapters", "seed_global_gtm_capability_adapters_policy")')
        >= 2
    )
    assert "DELETE FROM capability_adapters" in migration
    assert "DELETE FROM capabilities" in migration


def test_gtm_catalog_seed_migration_evidence_expectations_match_api_list_contract() -> None:
    migration = Path("alembic/versions/0021_seed_gtm_capability_catalog.py").read_text(encoding="utf-8")

    assert '\'["approval_decision", "send_outcome"]\'::jsonb' in migration
    assert '\'["approval_decision", "delivery_outcome"]\'::jsonb' in migration


def test_adapter_side_effect_classification_expansion_runs_after_current_head() -> None:
    expansion = Path("alembic/versions/0023_expand_adapter_side_effects.py").read_text(encoding="utf-8")
    seed = Path("alembic/versions/0021_seed_gtm_capability_catalog.py").read_text(encoding="utf-8")

    assert 'revision = "0023_adapter_side_effects"' in expansion
    assert 'down_revision = "0022_add_business_profiles"' in expansion
    assert 'down_revision = "0020_expand_lifecycle_checks"' in seed
    assert "ck_capability_adapters_side_effect_classification" in expansion
    assert "external_read" in expansion
    assert "external_write" in expansion
    assert "external_send" in expansion
    assert "external_publish" in expansion
    assert "op.drop_constraint" in expansion
    assert "op.create_check_constraint" in expansion


def test_gtm_seed_remains_legacy_constraint_compatible_until_post_head_expansion() -> None:
    seed = Path("alembic/versions/0021_seed_gtm_capability_catalog.py").read_text(encoding="utf-8")
    expansion = Path("alembic/versions/0023_expand_adapter_side_effects.py").read_text(encoding="utf-8")

    assert "'external_side_effect'," in seed
    assert "'external_send'," not in seed
    assert "gtm_outbound_email_adapter" in expansion
    assert "SET side_effect_classification = 'external_send'" in expansion


def test_historical_adapter_constraint_remains_pre_expansion_for_upgrade_compatibility() -> None:
    initial = Path("alembic/versions/0012_capability_adapters.py").read_text(encoding="utf-8")

    assert "'external_side_effect')" in initial
    assert "external_send" not in initial
