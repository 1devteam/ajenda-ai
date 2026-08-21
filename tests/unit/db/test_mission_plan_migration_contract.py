from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_mission_plan_migration_has_single_head_and_short_revision_id() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    assert heads == ["0039_add_password_login"]
    assert len(heads[0]) <= 32


def test_mission_plan_migration_contains_tenant_indexes_jsonb_unique_active_plan_and_rls() -> None:
    migration = Path("alembic/versions/0017_add_mission_plans.py").read_text(encoding="utf-8")

    assert "mission_plans" in migration
    assert "ix_mission_plans_tenant_id" in migration
    assert "ix_mission_plans_mission_id" in migration
    assert "ix_mission_plans_mission_tenant" in migration
    assert "uq_mission_plans_active_mission_tenant" in migration
    assert "status IN ('draft', 'ready')" in migration
    assert "postgresql.JSONB" in migration
    assert "metadata_json" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "tenant_mission_plan_isolation" in migration
    assert "def downgrade" in migration


def test_mission_plan_status_hardening_migration_adds_valid_value_constraint() -> None:
    migration = Path("alembic/versions/0018_harden_mission_plan_status.py").read_text(encoding="utf-8")

    assert "ck_mission_plans_status" in migration
    assert "draft" in migration
    assert "ready" in migration
    assert "superseded" in migration
    assert "cancelled" in migration
    assert "op.create_check_constraint" in migration
    assert "op.drop_constraint" in migration


def test_mission_plan_backfill_migration_copies_legacy_metadata_into_durable_table() -> None:
    migration = Path("alembic/versions/0031_backfill_mission_plans_from_metadata.py").read_text(encoding="utf-8")

    assert "0031_backfill_mission_plans" in migration
    assert "build_mission_plan_contract_metadata_from_legacy_metadata" in migration
    assert "legacy_mission_plan_status_from_planning_status" in migration
    assert "mission_plans" in migration
    assert "metadata_json ?" in migration
    assert "legacy_v1" in migration
    assert "def downgrade" in migration
