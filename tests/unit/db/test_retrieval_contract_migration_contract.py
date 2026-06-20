from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_retrieval_contract_migration_has_single_head_and_short_revision_id() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    assert heads == ["0026_seed_ability_runtime"]
    assert len(heads[0]) <= 32


def test_retrieval_contract_migration_contains_tenant_indexes_jsonb_and_rls_policies() -> None:
    migration = Path("alembic/versions/0016_retrieval_contracts.py").read_text(encoding="utf-8")

    assert "retrieval_contracts" in migration
    assert "ix_retrieval_contracts_tenant_id" in migration
    assert "ix_retrieval_contracts_mission_id" in migration
    assert "postgresql.JSONB" in migration
    assert "retrieval_request" in migration
    assert "strategy_metadata" in migration
    assert "retrieval_filters" in migration
    assert "governance_constraints" in migration
    assert "returned_memory_references" in migration
    assert "trust_signal" in migration
    assert "provenance_metadata" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "tenant_retrieval_contract_isolation" in migration
    assert "def downgrade" in migration


def test_retrieval_contract_value_hardening_migration_adds_contract_constraints() -> None:
    migration = Path("alembic/versions/0019_harden_retrieval_contract_values.py").read_text(encoding="utf-8")

    assert "ck_retrieval_contracts_retrieval_status" in migration
    assert "ck_retrieval_contracts_retrieval_strategy" in migration
    for status in ("requested", "fulfilled", "rejected", "superseded", "revoked"):
        assert status in migration
    for strategy in ("semantic", "keyword", "hybrid", "operator_selected", "policy_selected", "procedural"):
        assert strategy in migration
    assert "op.create_check_constraint" in migration
    assert "op.drop_constraint" in migration


def test_retrieval_contract_superseded_by_reference_remains_loose_uuid_reference() -> None:
    migration = Path("alembic/versions/0016_retrieval_contracts.py").read_text(encoding="utf-8")

    assert "superseded_by_retrieval_id" in migration
    assert "ix_retrieval_contracts_superseded_by_retrieval_id" in migration
    assert 'ForeignKeyConstraint(["superseded_by_retrieval_id"]' not in migration
